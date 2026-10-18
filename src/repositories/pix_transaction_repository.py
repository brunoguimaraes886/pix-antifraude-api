from datetime import datetime
from typing import Optional

from sqlalchemy import and_, distinct, func

from database import Context
from models import Account, AnalysisStatus, PixTransaction, TransactionAnalysis
from utils.document_number import only_digits


def destination_filter(participant: str, branch: str, account_number: str):
    return and_(
        PixTransaction.destination_participant == participant,
        PixTransaction.destination_branch == branch,
        PixTransaction.destination_account_number == account_number,
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
        """Tentativas do pagador em [since, before) — qualquer decisão conta."""
        return (
            self.session.query(func.count(PixTransaction.id))
            .filter(
                PixTransaction.source_account_id == source_account_id,
                PixTransaction.transaction_date >= since,
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
