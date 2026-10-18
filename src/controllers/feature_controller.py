from collections import Counter
from datetime import date, datetime, timedelta
from typing import Iterable, List, Optional, Set

from constants import OUR_ISPB
from controllers.base_controller import BaseController
from engine.features import (
    BaselineFeatures,
    CustomerFeatures,
    DestinationFeatures,
    DestinationHistoryFeatures,
    DeviceFeatures,
    Features,
    FlowSideFeatures,
    FlowWindowFeatures,
    InternalAccountFeatures,
    PeriodFeatures,
    RelationshipFeatures,
    TransactionFeatures,
    VelocityFeatures,
)
from models import Account, AccountBaseline, AccountStatement, PixTransaction
from repositories import AccountBlockRepository, AccountStatementRepository, PixTransactionRepository
from utils.document_number import document_type
from utils.geo import distance_km
from utils.periods import DAY, Period, current_period, previous_period


class FeatureController(BaseController):
    """Monta o `Features`: tudo que o motor vai ver sobre um Pix.

    É aqui que o histórico vira número — janela de 24h, períodos diurno e
    noturno, taxa de passagem, razão de saída, contrapartes novas e
    repetidas, relação com o destino, aparelho, velocidade. O motor não
    consulta nada: recebe pronto.

    Tudo é relativo ao `moment` (a data do Pix, no fuso dele), e nunca ao
    relógio do servidor. O mesmo Pix, analisado de novo, vê o mesmo passado.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.account_block_repository = AccountBlockRepository(self.context)
        self.account_statement_repository = AccountStatementRepository(self.context)
        self.pix_transaction_repository = PixTransactionRepository(self.context)

    def build(
        self,
        pix: PixTransaction,
        moment: datetime,
        payer: Account,
        payer_baseline: AccountBaseline,
        destination_account: Optional[Account],
        destination_baseline: Optional[AccountBaseline],
    ) -> Features:
        payer_features = self._internal_account(payer, payer_baseline, moment)

        destination_account_features = None
        if destination_account is not None:
            destination_account_features = self._internal_account(destination_account, destination_baseline, moment)

        return Features(
            transaction=self._transaction(pix, moment, payer_features),
            payer=payer_features,
            destination=self._destination(pix, moment, destination_account, destination_account_features),
            relationship=self._relationship(pix, moment, payer),
            device=self._device(pix, moment, payer),
            velocity=self._velocity(pix, moment, payer),
        )

    # ────────────────────────────────────────────────────────────────
    # A transação
    # ────────────────────────────────────────────────────────────────

    def _transaction(self, pix: PixTransaction, moment: datetime, payer: InternalAccountFeatures) -> TransactionFeatures:
        amount = pix.amount
        baseline = payer.baseline

        return TransactionFeatures(
            pix_id=pix.pix_id,
            amount=amount,
            transaction_date=moment,
            local_hour=moment.hour,
            weekday=moment.weekday(),
            period=current_period(moment).kind,
            ratio_to_balance=_ratio(amount, payer.balance),
            ratio_to_avg_out=_ratio(amount, baseline.avg_out_amount),
            ratio_to_p90_out=_ratio(amount, baseline.p90_out_amount),
        )

    # ────────────────────────────────────────────────────────────────
    # Conta nossa: perfil, habitual e fluxo recente
    # ────────────────────────────────────────────────────────────────

    def _internal_account(self, account: Account, baseline: AccountBaseline, moment: datetime) -> InternalAccountFeatures:
        customer = account.customer
        last_24h, current, previous = self._flows(account, moment)

        return InternalAccountFeatures(
            account_key=account.account_key,
            customer=CustomerFeatures(
                document_type=document_type(customer.document_number),
                age_years=_years_between(customer.birth_date, moment.date()),
            ),
            account_age_days=(moment - account.opening_date).days,
            balance=account.balance,
            daily_limit=account.daily_limit,
            nightly_limit=account.nightly_limit,
            is_blocked=self.account_block_repository.is_blocked(account.id, moment),
            baseline=_baseline_features(baseline),
            last_24h=last_24h,
            current_period=current,
            previous_period=previous,
        )

    def _flows(self, account: Account, moment: datetime):
        """As três janelas do extrato: últimas 24h, período atual e o anterior.

        Os dois períodos cabem dentro das 24h (o mais antigo começa no
        máximo 24h antes do Pix), então uma leitura do extrato serve às
        três janelas.
        """
        since = moment - timedelta(hours=24)
        rows = self.account_statement_repository.list_since(account.id, since)

        counterparties = {row.counterparty() for row in rows}
        known_before = self.account_statement_repository.counterparties_seen_before(account.id, since, counterparties)

        current = current_period(moment)
        previous = previous_period(current)

        last_24h = _flow_window(account.balance, rows, known_before, since, moment)
        current_window = _flow_window(account.balance, rows, known_before, current.start, moment)
        previous_window = _flow_window(account.balance, rows, known_before, previous.start, previous.end)

        return (
            last_24h,
            _period_features(current_window, current, True, account),
            _period_features(previous_window, previous, False, account),
        )

    # ────────────────────────────────────────────────────────────────
    # O destino
    # ────────────────────────────────────────────────────────────────

    def _destination(
        self,
        pix: PixTransaction,
        moment: datetime,
        destination_account: Optional[Account],
        destination_account_features: Optional[InternalAccountFeatures],
    ) -> DestinationFeatures:
        destination = _destination_tuple(pix)

        # Conta nossa: a idade vem do nosso cadastro. De outro banco: só
        # temos o opening_date que veio no payload.
        opening_date = pix.destination_opening_date
        if destination_account is not None:
            opening_date = destination_account.opening_date

        history = self.pix_transaction_repository.destination_history(
            destination, moment, moment - timedelta(hours=24), pix.id
        )

        return DestinationFeatures(
            is_internal=pix.destination_participant == OUR_ISPB,
            participant=pix.destination_participant,
            document_type=document_type(pix.destination_document_number),
            account_age_days=(moment - opening_date).days,
            account=destination_account_features,
            history=DestinationHistoryFeatures(**history),
            dict=None,
        )

    def _relationship(self, pix: PixTransaction, moment: datetime, payer: Account) -> RelationshipFeatures:
        destination = _destination_tuple(pix)

        stats = self.account_statement_repository.relationship_stats(
            payer.id, destination, moment, moment - timedelta(days=30)
        )
        attempts = self.pix_transaction_repository.count_attempts_to_destination(payer.id, destination, moment, pix.id)

        return RelationshipFeatures(previous_attempts=attempts, **stats)

    # ────────────────────────────────────────────────────────────────
    # De onde saiu o Pix
    # ────────────────────────────────────────────────────────────────

    def _device(self, pix: PixTransaction, moment: datetime, payer: Account) -> DeviceFeatures:
        stats = self.pix_transaction_repository.device_stats(
            payer.id, pix.device_id, pix.ip, moment, moment - timedelta(days=30), pix.id
        )

        distance = None
        minutes_since = None

        if pix.latitude is not None and pix.longitude is not None:
            last_located = self.pix_transaction_repository.last_located(payer.id, moment, pix.id)

            if last_located is not None:
                distance = round(distance_km(last_located.latitude, last_located.longitude, pix.latitude, pix.longitude), 3)
                minutes_since = round((moment - last_located.transaction_date).total_seconds() / 60, 2)

        return DeviceFeatures(
            device_id=pix.device_id,
            channel=pix.channel,
            ip=pix.ip,
            latitude=pix.latitude,
            longitude=pix.longitude,
            distance_from_last_km=distance,
            minutes_since_last_location=minutes_since,
            **stats,
        )

    def _velocity(self, pix: PixTransaction, moment: datetime, payer: Account) -> VelocityFeatures:
        """Tentativas, não só Pix aprovados: 2FA e rejeitado também contam."""
        repository = self.pix_transaction_repository
        last_attempt_at = repository.last_attempt_at(payer.id, moment, pix.id)

        seconds_since = None
        if last_attempt_at is not None:
            seconds_since = round((moment - last_attempt_at).total_seconds(), 3)

        return VelocityFeatures(
            attempts_last_1h=repository.count_attempts(payer.id, moment - timedelta(hours=1), moment, pix.id),
            attempts_last_24h=repository.count_attempts(payer.id, moment - timedelta(hours=24), moment, pix.id),
            attempts_current_period=repository.count_attempts(payer.id, current_period(moment).start, moment, pix.id),
            seconds_since_last_attempt=seconds_since,
        )


# ────────────────────────────────────────────────────────────────────
# As contas, sem banco: funções puras sobre o que já foi lido
# ────────────────────────────────────────────────────────────────────


def _flow_window(
    balance_now: int,
    rows: List[AccountStatement],
    known_before_rows: Set[tuple],
    start: datetime,
    end: datetime,
) -> FlowWindowFeatures:
    """O que entrou e saiu em [start, end).

    O saldo do início não está gravado em lugar nenhum: ele é o saldo de
    agora desfazendo tudo que moveu a partir de `start` (por isso `rows`
    traz também o que veio depois do Pix).

    Contraparte "nova" é a que nunca apareceu no extrato antes de `start`.
    """
    moved_in = sum(row.amount for row in rows if row.direction == AccountStatement.IN and row.occurred_at >= start)
    moved_out = sum(row.amount for row in rows if row.direction == AccountStatement.OUT and row.occurred_at >= start)
    balance_at_start = max(0, balance_now - moved_in + moved_out)

    known = set(known_before_rows)
    for row in rows:
        if row.occurred_at < start:
            known.add(row.counterparty())

    window_rows = [row for row in rows if start <= row.occurred_at < end]
    inflow = _flow_side([row for row in window_rows if row.direction == AccountStatement.IN], known)
    outflow = _flow_side([row for row in window_rows if row.direction == AccountStatement.OUT], known)

    return FlowWindowFeatures(
        start=start,
        end=end,
        balance_at_start=balance_at_start,
        inflow=inflow,
        outflow=outflow,
        pass_through_rate=_ratio(outflow.amount, inflow.amount),
        exit_ratio=_ratio(outflow.amount, balance_at_start + inflow.amount),
    )


def _flow_side(rows: Iterable[AccountStatement], known: Set[tuple]) -> FlowSideFeatures:
    rows = list(rows)
    per_counterparty = Counter(row.counterparty() for row in rows)

    return FlowSideFeatures(
        amount=sum(row.amount for row in rows),
        count=len(rows),
        distinct_counterparties=len(per_counterparty),
        new_counterparties=len([cp for cp in per_counterparty if cp not in known]),
        repeated_counterparties=len([cp for cp, times in per_counterparty.items() if times >= 2]),
    )


def _period_features(window: FlowWindowFeatures, period: Period, is_current: bool, account: Account) -> PeriodFeatures:
    limit = account.daily_limit if period.kind == DAY else account.nightly_limit

    return PeriodFeatures(**vars(window), kind=period.kind, is_current=is_current, limit=limit)


def _baseline_features(baseline: AccountBaseline) -> BaselineFeatures:
    return BaselineFeatures(
        baseline_date=baseline.baseline_date,
        history_days=baseline.history_days,
        avg_out_amount=baseline.avg_out_amount,
        p90_out_amount=baseline.p90_out_amount,
        avg_in_amount=baseline.avg_in_amount,
        p90_in_amount=baseline.p90_in_amount,
        avg_daily_out_count=_float(baseline.avg_daily_out_count),
        avg_daily_in_count=_float(baseline.avg_daily_in_count),
        account_block_count=baseline.account_block_count,
        rejected_pix_out_count=baseline.rejected_pix_out_count,
        rejected_pix_in_count=baseline.rejected_pix_in_count,
    )


def _destination_tuple(pix: PixTransaction) -> tuple:
    return (pix.destination_participant, pix.destination_branch, pix.destination_account_number)


def _years_between(start: date, end: date) -> int:
    years = end.year - start.year

    if (end.month, end.day) < (start.month, start.day):
        years = years - 1

    return years


def _ratio(numerator, denominator) -> Optional[float]:
    """numerador / denominador — ou None, quando não há base pra comparar."""
    if denominator is None or denominator <= 0:
        return None

    return round(numerator / denominator, 4)


def _float(value) -> Optional[float]:
    if value is None:
        return None

    return float(value)
