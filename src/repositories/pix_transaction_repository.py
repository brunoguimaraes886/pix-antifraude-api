from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import and_, distinct, func, or_, select

from database import Context
from engine.reasons import NOT_SUSPICION_CODES, OPERATIONAL_CODES
from models import Account, AnalysisReason, AnalysisStatus, PixTransaction, TransactionAnalysis
from utils.document_number import only_digits


def destination_filter(participant: str, branch: str, account_number: str):
    return and_(
        PixTransaction.destination_participant == participant,
        PixTransaction.destination_branch == branch,
        PixTransaction.destination_account_number == account_number,
    )


def destination_or_document_filter(destination: tuple, document_number: str):
    """Mesmo destino = mesma conta OU mesmo CPF/CNPJ (o golpista troca de conta, não de CPF)."""
    return or_(destination_filter(*destination), PixTransaction.destination_document_number == document_number)


def _pix_with_reason(condition, statuses=None):
    """Os Pix cuja análise tem algum motivo que atende `condition` (e, se pedido, um destes status)."""
    query = select(TransactionAnalysis.pix_transaction_id).join(
        AnalysisReason, AnalysisReason.analysis_id == TransactionAnalysis.id
    )

    if statuses is not None:
        query = query.join(AnalysisStatus, AnalysisStatus.id == TransactionAnalysis.status_id).where(
            AnalysisStatus.enumerator.in_(statuses)
        )

    return query.where(condition)


def not_operational():
    """Tira as recusas operacionais (sem saldo, conta inexistente): não dizem nada sobre fraude."""
    return PixTransaction.id.notin_(_pix_with_reason(AnalysisReason.reason_code.in_(OPERATIONAL_CODES)))


def suspicion(statuses: list):
    """Pix barrado por suspeita: algum motivo que não é limite nem operacional."""
    return PixTransaction.id.in_(_pix_with_reason(AnalysisReason.reason_code.notin_(NOT_SUSPICION_CODES), statuses))


def approved():
    return PixTransaction.id.in_(
        select(TransactionAnalysis.pix_transaction_id)
        .join(AnalysisStatus, AnalysisStatus.id == TransactionAnalysis.status_id)
        .where(AnalysisStatus.enumerator == AnalysisStatus.APPROVED)
    )


class PixTransactionRepository:
    """Tudo que chegou no POST — e as perguntas pontuais sobre esse histórico.

    Toda consulta de histórico recebe `before` (o momento do Pix analisado)
    e `exclude_id` (o próprio Pix, já gravado): o histórico é o que veio
    ANTES, nunca o Pix que está sendo decidido.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_by_pix_id(self, pix_id: str) -> Optional[PixTransaction]:
        return self.session.query(PixTransaction).filter(PixTransaction.pix_id == pix_id).first()

    def create(
        self,
        payload: dict,
        transaction_date: datetime,
        destination_opening_date: datetime,
        source_account: Optional[Account],
        destination_account: Optional[Account],
    ) -> PixTransaction:
        destination = payload["destination_account"]
        source = payload["source"]
        geolocation = source.get("geolocation")

        pix = PixTransaction()
        pix.pix_id = payload["id"]
        pix.amount = payload["amount"]
        pix.transaction_date = transaction_date
        pix.source_account_id = source_account.id if source_account is not None else None
        pix.destination_participant = destination["participant"]
        pix.destination_branch = destination["branch"]
        pix.destination_account_number = destination["account_number"]
        pix.destination_opening_date = destination_opening_date
        pix.destination_document_number = only_digits(destination["owner"]["document_number"])
        pix.destination_account_id = destination_account.id if destination_account is not None else None
        pix.device_id = source["device_id"]
        pix.channel = source["channel"]
        pix.ip = source["ip"]
        pix.latitude = geolocation["latitude"] if geolocation else None
        pix.longitude = geolocation["longitude"] if geolocation else None
        pix.payload = payload

        self.session.add(pix)
        return pix

    def count_attempts_to_destination(
        self, source_account_id: int, destination: tuple, before: datetime, exclude_id: int
    ) -> int:
        return (
            self.session.query(func.count(PixTransaction.id))
            .filter(
                PixTransaction.source_account_id == source_account_id,
                destination_filter(*destination),
                PixTransaction.transaction_date < before,
                PixTransaction.id != exclude_id,
            )
            .scalar()
        )

    def destination_history(self, destination: tuple, before: datetime, since_24h: datetime, exclude_id: int) -> dict:
        """Tudo que já chegou aqui com esta conta como destino, de qualquer pagador nosso."""
        previous = [
            destination_filter(*destination),
            PixTransaction.transaction_date < before,
            PixTransaction.id != exclude_id,
        ]

        by_status = (
            self.session.query(
                AnalysisStatus.enumerator,
                func.count(PixTransaction.id),
                func.coalesce(func.sum(PixTransaction.amount), 0),
            )
            .join(TransactionAnalysis, TransactionAnalysis.pix_transaction_id == PixTransaction.id)
            .join(AnalysisStatus, AnalysisStatus.id == TransactionAnalysis.status_id)
            .filter(*previous)
            .group_by(AnalysisStatus.enumerator)
            .all()
        )
        counts = {enumerator: (count, int(amount)) for enumerator, count, amount in by_status}

        total_count, distinct_payers, first_seen_at, last_seen_at = (
            self.session.query(
                func.count(PixTransaction.id),
                func.count(distinct(PixTransaction.source_account_id)),
                func.min(PixTransaction.transaction_date),
                func.max(PixTransaction.transaction_date),
            )
            .filter(*previous)
            .one()
        )

        last_24h_count, last_24h_distinct_payers = (
            self.session.query(func.count(PixTransaction.id), func.count(distinct(PixTransaction.source_account_id)))
            .filter(*previous, PixTransaction.transaction_date >= since_24h)
            .one()
        )

        last_24h_approved_amount = (
            self.session.query(func.coalesce(func.sum(PixTransaction.amount), 0))
            .join(TransactionAnalysis, TransactionAnalysis.pix_transaction_id == PixTransaction.id)
            .join(AnalysisStatus, AnalysisStatus.id == TransactionAnalysis.status_id)
            .filter(
                *previous,
                PixTransaction.transaction_date >= since_24h,
                AnalysisStatus.enumerator == AnalysisStatus.APPROVED,
            )
            .scalar()
        )

        return {
            "total_count": total_count,
            "approved_count": counts.get(AnalysisStatus.APPROVED, (0, 0))[0],
            "two_factor_count": counts.get(AnalysisStatus.TWO_FACTOR_REQUIRED, (0, 0))[0],
            "rejected_count": counts.get(AnalysisStatus.REJECTED, (0, 0))[0],
            "approved_amount": counts.get(AnalysisStatus.APPROVED, (0, 0))[1],
            "distinct_payers": distinct_payers,
            "first_seen_at": first_seen_at,
            "last_seen_at": last_seen_at,
            "last_24h_count": last_24h_count,
            "last_24h_distinct_payers": last_24h_distinct_payers,
            "last_24h_approved_amount": int(last_24h_approved_amount),
        }

    def device_stats(
        self, source_account_id: int, device_id: str, ip: str, before: datetime, since_30d: datetime, exclude_id: int
    ) -> dict:
        previous = [
            PixTransaction.source_account_id == source_account_id,
            PixTransaction.transaction_date < before,
            PixTransaction.id != exclude_id,
        ]

        device_uses, device_first_seen_at = (
            self.session.query(func.count(PixTransaction.id), func.min(PixTransaction.transaction_date))
            .filter(*previous, PixTransaction.device_id == device_id)
            .one()
        )

        device_approved_uses = (
            self.session.query(func.count(PixTransaction.id))
            .join(TransactionAnalysis, TransactionAnalysis.pix_transaction_id == PixTransaction.id)
            .join(AnalysisStatus, AnalysisStatus.id == TransactionAnalysis.status_id)
            .filter(
                *previous,
                PixTransaction.device_id == device_id,
                AnalysisStatus.enumerator == AnalysisStatus.APPROVED,
            )
            .scalar()
        )

        ip_uses = self.session.query(func.count(PixTransaction.id)).filter(*previous, PixTransaction.ip == ip).scalar()

        distinct_devices = (
            self.session.query(func.count(distinct(PixTransaction.device_id)))
            .filter(*previous, PixTransaction.transaction_date >= since_30d)
            .scalar()
        )

        return {
            "device_previous_uses": device_uses,
            "device_previous_approved_uses": device_approved_uses,
            "device_first_seen_at": device_first_seen_at,
            "ip_previous_uses": ip_uses,
            "distinct_devices_last_30d": distinct_devices,
        }

    def last_located(self, source_account_id: int, before: datetime, exclude_id: int) -> Optional[PixTransaction]:
        """O último Pix do pagador que veio com geolocalização."""
        return (
            self.session.query(PixTransaction)
            .filter(
                PixTransaction.source_account_id == source_account_id,
                PixTransaction.transaction_date < before,
                PixTransaction.id != exclude_id,
                PixTransaction.latitude.isnot(None),
                PixTransaction.longitude.isnot(None),
            )
            .order_by(PixTransaction.transaction_date.desc(), PixTransaction.id.desc())
            .first()
        )

    def count_attempts(self, source_account_id: int, since: datetime, before: datetime, exclude_id: int) -> int:
        """Tentativas do pagador em [since, before): qualquer decisão do motor conta.

        As recusas operacionais (sem saldo, conta inexistente) ficam de fora:
        não dizem nada sobre fraude.
        """
        return (
            self.session.query(func.count(PixTransaction.id))
            .filter(
                PixTransaction.source_account_id == source_account_id,
                PixTransaction.transaction_date >= since,
                PixTransaction.transaction_date < before,
                PixTransaction.id != exclude_id,
                not_operational(),
            )
            .scalar()
        )

    # ────────────────────────────────────────────────────────────────
    # Relação com o destino nas últimas 24h (insistência, fracionamento)
    # ────────────────────────────────────────────────────────────────

    def relationship_24h(
        self,
        source_account_id: int,
        destination: tuple,
        document_number: str,
        since: datetime,
        before: datetime,
        exclude_id: int,
    ) -> dict:
        window = [
            PixTransaction.source_account_id == source_account_id,
            PixTransaction.transaction_date >= since,
            PixTransaction.transaction_date < before,
            PixTransaction.id != exclude_id,
            not_operational(),
        ]
        same_account = destination_filter(*destination)

        attempts = self.session.query(func.count(PixTransaction.id)).filter(*window, same_account).scalar()

        last_attempt = (
            self.session.query(PixTransaction.amount)
            .filter(*window, same_account)
            .order_by(PixTransaction.transaction_date.desc(), PixTransaction.id.desc())
            .first()
        )

        blocked = (
            self.session.query(func.count(PixTransaction.id))
            .filter(*window, same_account, suspicion([AnalysisStatus.TWO_FACTOR_REQUIRED, AnalysisStatus.REJECTED]))
            .scalar()
        )

        fraud_rejections = (
            self.session.query(func.count(PixTransaction.id))
            .filter(
                *window,
                destination_or_document_filter(destination, document_number),
                suspicion([AnalysisStatus.REJECTED]),
            )
            .scalar()
        )

        return {
            "attempts_to_destination_24h": attempts,
            "last_attempt_amount": last_attempt[0] if last_attempt is not None else None,
            "blocked_attempts_24h": blocked,
            "fraud_rejections_24h": fraud_rejections,
        }

    # ────────────────────────────────────────────────────────────────
    # O destino visto por OUTROS clientes nossos
    # ────────────────────────────────────────────────────────────────

    def new_payers(
        self,
        destination: tuple,
        document_number: str,
        source_account_id: int,
        since: datetime,
        before: datetime,
        exclude_id: int,
    ) -> int:
        """Outros pagadores cujo PRIMEIRO Pix para este destino caiu em [since, before) — o fan-in."""
        first_by_payer = (
            self.session.query(
                PixTransaction.source_account_id,
                func.min(PixTransaction.transaction_date).label("first_at"),
            )
            .filter(
                destination_or_document_filter(destination, document_number),
                PixTransaction.source_account_id.isnot(None),
                PixTransaction.source_account_id != source_account_id,
                PixTransaction.transaction_date < before,
                PixTransaction.id != exclude_id,
                not_operational(),
            )
            .group_by(PixTransaction.source_account_id)
            .subquery()
        )

        return (
            self.session.query(func.count())
            .select_from(first_by_payer)
            .filter(first_by_payer.c.first_at >= since)
            .scalar()
        )

    def fraud_rejected_payers(
        self,
        destination: tuple,
        document_number: str,
        source_account_id: int,
        since: datetime,
        before: datetime,
        exclude_id: int,
    ) -> int:
        """Outros pagadores com Pix para este destino rejeitado por suspeita SOBRE O DESTINO.

        "Sobre o destino" é o que o motor gravou em `decision`: a família
        destino dominou o score ou uma regra do DICT disparou.
        """
        return (
            self.session.query(func.count(distinct(PixTransaction.source_account_id)))
            .join(TransactionAnalysis, TransactionAnalysis.pix_transaction_id == PixTransaction.id)
            .join(AnalysisStatus, AnalysisStatus.id == TransactionAnalysis.status_id)
            .filter(
                destination_or_document_filter(destination, document_number),
                PixTransaction.source_account_id.isnot(None),
                PixTransaction.source_account_id != source_account_id,
                PixTransaction.transaction_date >= since,
                PixTransaction.transaction_date < before,
                PixTransaction.id != exclude_id,
                AnalysisStatus.enumerator == AnalysisStatus.REJECTED,
                TransactionAnalysis.decision["destination_evidence"].astext == "true",
            )
            .scalar()
        )

    # ────────────────────────────────────────────────────────────────
    # Aparelho cadastrado (IN BCB 491): uso aprovado em dias distintos
    # ────────────────────────────────────────────────────────────────

    def device_registration(
        self, source_account_id: int, device_ids: List[str], since: datetime, before: datetime, exclude_id: int
    ) -> Dict[str, Tuple[int, Optional[datetime], Optional[datetime]]]:
        """Por aparelho: (dias distintos com Pix aprovado, primeiro aprovado, último uso).

        Só a janela [since, before): aparelho sem uso há mais de 12 meses
        deixa de ser cadastrado.
        """
        if not device_ids:
            return {}

        window = [
            PixTransaction.source_account_id == source_account_id,
            PixTransaction.device_id.in_(device_ids),
            PixTransaction.transaction_date >= since,
            PixTransaction.transaction_date < before,
            PixTransaction.id != exclude_id,
        ]

        approved_rows = (
            self.session.query(
                PixTransaction.device_id,
                func.count(distinct(func.date(PixTransaction.transaction_date))),
                func.min(PixTransaction.transaction_date),
            )
            .filter(*window, approved())
            .group_by(PixTransaction.device_id)
            .all()
        )
        last_used_rows = (
            self.session.query(PixTransaction.device_id, func.max(PixTransaction.transaction_date))
            .filter(*window)
            .group_by(PixTransaction.device_id)
            .all()
        )

        approved_by_device = {device: (days, first) for device, days, first in approved_rows}
        result = {}
        for device, last_used_at in last_used_rows:
            days, first = approved_by_device.get(device, (0, None))
            result[device] = (days, first, last_used_at)

        return result

    def approved_devices_count(self, source_account_id: int, before: datetime, exclude_id: int) -> int:
        return (
            self.session.query(func.count(distinct(PixTransaction.device_id)))
            .filter(
                PixTransaction.source_account_id == source_account_id,
                PixTransaction.transaction_date < before,
                PixTransaction.id != exclude_id,
                approved(),
            )
            .scalar()
        )

    def approved_by_device(self, source_account_id: int, since: datetime, before: datetime, exclude_id: int) -> list:
        """(aparelho, valor) de cada Pix aprovado do pagador em [since, before)."""
        return (
            self.session.query(PixTransaction.device_id, PixTransaction.amount)
            .filter(
                PixTransaction.source_account_id == source_account_id,
                PixTransaction.transaction_date >= since,
                PixTransaction.transaction_date < before,
                PixTransaction.id != exclude_id,
                approved(),
            )
            .all()
        )

    def devices_with_amount_between(
        self, source_account_id: int, minimum: int, maximum: int, since: datetime, before: datetime, exclude_id: int
    ) -> List[str]:
        """O aparelho de cada Pix do pagador com valor em [minimum, maximum], sem as recusas operacionais."""
        rows = (
            self.session.query(PixTransaction.device_id)
            .filter(
                PixTransaction.source_account_id == source_account_id,
                PixTransaction.amount >= minimum,
                PixTransaction.amount <= maximum,
                PixTransaction.transaction_date >= since,
                PixTransaction.transaction_date < before,
                PixTransaction.id != exclude_id,
                not_operational(),
            )
            .all()
        )

        return [row[0] for row in rows]

    def other_accounts_with_device(self, device_id: str, source_account_id: int, since: datetime, before: datetime) -> int:
        return (
            self.session.query(func.count(distinct(PixTransaction.source_account_id)))
            .filter(
                PixTransaction.device_id == device_id,
                PixTransaction.source_account_id.isnot(None),
                PixTransaction.source_account_id != source_account_id,
                PixTransaction.transaction_date >= since,
                PixTransaction.transaction_date < before,
            )
            .scalar()
        )

    def channel_previous_uses(self, source_account_id: int, channel: str, before: datetime, exclude_id: int) -> int:
        return (
            self.session.query(func.count(PixTransaction.id))
            .filter(
                PixTransaction.source_account_id == source_account_id,
                PixTransaction.channel == channel,
                PixTransaction.transaction_date < before,
                PixTransaction.id != exclude_id,
            )
            .scalar()
        )

    def last_attempt_at(self, source_account_id: int, before: datetime, exclude_id: int) -> Optional[datetime]:
        return (
            self.session.query(func.max(PixTransaction.transaction_date))
            .filter(
                PixTransaction.source_account_id == source_account_id,
                PixTransaction.transaction_date < before,
                PixTransaction.id != exclude_id,
            )
            .scalar()
        )
