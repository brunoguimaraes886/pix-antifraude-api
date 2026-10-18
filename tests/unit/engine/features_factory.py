"""Um Features de cliente comum, pronto pra ser alterado em cada teste.

O padrão é um Pix "limpo": cliente com histórico, destino de outro banco
que o DICT conhece sem marcação, valor pequeno, de dia. Cada teste muda
só o campo que importa pra regra que ele testa.
"""

from datetime import date, datetime, timedelta, timezone

from engine.features import (
    DICT_OK,
    BaselineFeatures,
    CustomerFeatures,
    DestinationFeatures,
    DestinationHistoryFeatures,
    DeviceFeatures,
    DictFeatures,
    Features,
    FlowSideFeatures,
    FlowWindowFeatures,
    InternalAccountFeatures,
    PeriodFeatures,
    RelationshipFeatures,
    TransactionFeatures,
    VelocityFeatures,
)

SAO_PAULO = timezone(timedelta(hours=-3))
MOMENT = datetime(2026, 10, 17, 14, 0, tzinfo=SAO_PAULO)


def flow_side(amount: int = 0, count: int = 0) -> FlowSideFeatures:
    return FlowSideFeatures(
        amount=amount,
        count=count,
        distinct_counterparties=count,
        new_counterparties=0,
        repeated_counterparties=0,
    )


def flow_window(start: datetime, end: datetime, out_amount: int = 0) -> dict:
    return dict(
        start=start,
        end=end,
        balance_at_start=500000,
        inflow=flow_side(),
        outflow=flow_side(out_amount, 1 if out_amount else 0),
        pass_through_rate=None,
        exit_ratio=out_amount / 500000,
    )


def internal_account(balance: int = 500000) -> InternalAccountFeatures:
    return InternalAccountFeatures(
        account_key="a0000000-0000-4000-8000-000000000001",
        customer=CustomerFeatures(document_type="PF", age_years=41),
        account_age_days=600,
        balance=balance,
        daily_limit=1000000,
        nightly_limit=100000,
        is_blocked=False,
        baseline=BaselineFeatures(
            baseline_date=date(2026, 10, 17),
            history_days=30,
            avg_out_amount=15000,
            p90_out_amount=40000,
            avg_in_amount=200000,
            p90_in_amount=850000,
            avg_daily_out_count=0.8,
            avg_daily_in_count=0.2,
            account_block_count=0,
            rejected_pix_out_count=0,
            rejected_pix_in_count=0,
            night_out_share=0.2,
        ),
        last_24h=FlowWindowFeatures(**flow_window(MOMENT - timedelta(hours=24), MOMENT)),
        current_period=PeriodFeatures(
            **flow_window(MOMENT.replace(hour=6), MOMENT), kind="day", is_current=True, limit=1000000
        ),
        previous_period=PeriodFeatures(
            **flow_window(MOMENT.replace(hour=6) - timedelta(hours=8), MOMENT.replace(hour=6)),
            kind="night",
            is_current=False,
            limit=100000,
        ),
    )


def clean_features(amount: int = 10000) -> Features:
    return Features(
        transaction=TransactionFeatures(
            pix_id="pix-unit-1",
            amount=amount,
            transaction_date=MOMENT,
            local_hour=MOMENT.hour,
            weekday=MOMENT.weekday(),
            period="day",
            ratio_to_balance=amount / 500000,
            ratio_to_avg_out=amount / 15000,
            ratio_to_p90_out=amount / 40000,
        ),
        payer=internal_account(),
        destination=DestinationFeatures(
            is_internal=False,
            participant="60701190",
            document_type="PF",
            account_age_days=900,
            account=None,
            history=DestinationHistoryFeatures(
                total_count=3,
                approved_count=3,
                two_factor_count=0,
                rejected_count=0,
                approved_amount=30000,
                distinct_payers=1,
                first_seen_at=MOMENT - timedelta(days=60),
                last_seen_at=MOMENT - timedelta(days=5),
                last_24h_count=0,
                last_24h_distinct_payers=0,
                last_24h_approved_amount=0,
            ),
            dict=DictFeatures(
                status=DICT_OK,
                response={"account": {"fraud_markers": []}, "owner": {"fraud_markers": []}},
                fetched_at=MOMENT,
            ),
        ),
        relationship=RelationshipFeatures(
            previous_out_count=3,
            previous_out_amount=30000,
            max_previous_out_amount=12000,
            first_out_at=MOMENT - timedelta(days=60),
            last_out_at=MOMENT - timedelta(days=5),
            out_days_last_30d=1,
            previous_in_count=0,
            previous_attempts=3,
        ),
        device=DeviceFeatures(
            device_id="dvc-1",
            channel="app",
            ip="198.51.100.23",
            device_previous_uses=40,
            device_previous_approved_uses=40,
            device_first_seen_at=MOMENT - timedelta(days=200),
            ip_previous_uses=10,
            distinct_devices_last_30d=1,
            latitude=-23.56,
            longitude=-46.65,
            distance_from_last_km=0.4,
            minutes_since_last_location=600.0,
            # Aparelho cadastrado: Pix aprovado em muitos dias, o primeiro há 200 dias.
            approved_devices_count=1,
            approved_days=40,
            first_approved_at=MOMENT - timedelta(days=200),
            last_used_at=MOMENT - timedelta(days=1),
            other_accounts_last_30d=0,
            channel_previous_uses=40,
        ),
        velocity=VelocityFeatures(
            attempts_last_1h=0,
            attempts_last_24h=1,
            attempts_current_period=0,
            seconds_since_last_attempt=36000.0,
        ),
    )


# ────────────────────────────────────────────────────────────────────
# Ajustes para montar cenários (4.2, seção 10). Cada um muda só o que diz.
# ────────────────────────────────────────────────────────────────────


def payer_profile(
    f: Features,
    balance: int = None,
    p90: int = None,
    daily_out: float = None,
    daily_in: float = None,
    avg_in: int = None,
    history_days: int = None,
    age_days: int = None,
    night_share: float = None,
    document_type: str = None,
) -> Features:
    payer = f.payer
    baseline = payer.baseline
    if balance is not None:
        payer.balance = balance
    if p90 is not None:
        baseline.p90_out_amount = p90
    if daily_out is not None:
        baseline.avg_daily_out_count = daily_out
    if daily_in is not None:
        baseline.avg_daily_in_count = daily_in
    if avg_in is not None:
        baseline.avg_in_amount = avg_in
    if history_days is not None:
        baseline.history_days = history_days
    if age_days is not None:
        payer.account_age_days = age_days
    if night_share is not None:
        baseline.night_out_share = night_share
    if document_type is not None:
        payer.customer.document_type = document_type
    return f


def limits(f: Features, daily: int = None, nightly: int = None) -> Features:
    if daily is not None:
        f.payer.daily_limit = daily
    if nightly is not None:
        f.payer.nightly_limit = nightly
    return f


def new_destination(f: Features, age_days: int = 900, document_type: str = "PF") -> Features:
    """Um destino que o pagador nunca pagou e que ninguém aqui conhece."""
    f.destination.account_age_days = age_days
    f.destination.document_type = document_type
    f.destination.history = DestinationHistoryFeatures(
        total_count=0,
        approved_count=0,
        two_factor_count=0,
        rejected_count=0,
        approved_amount=0,
        distinct_payers=0,
        first_seen_at=None,
        last_seen_at=None,
        last_24h_count=0,
        last_24h_distinct_payers=0,
        last_24h_approved_amount=0,
    )
    f.relationship = RelationshipFeatures(
        previous_out_count=0,
        previous_out_amount=0,
        max_previous_out_amount=None,
        first_out_at=None,
        last_out_at=None,
        out_days_last_30d=0,
        previous_in_count=0,
        previous_attempts=0,
    )
    return f


def paid_before(f: Features, count: int, total: int, largest: int, first_days_ago: float, last_days_ago: float = None):
    """O pagador já pagou este destino `count` vezes."""
    relationship = f.relationship
    relationship.previous_out_count = count
    relationship.previous_out_amount = total
    relationship.max_previous_out_amount = largest
    relationship.first_out_at = MOMENT - timedelta(days=first_days_ago)
    relationship.last_out_at = MOMENT - timedelta(days=last_days_ago if last_days_ago is not None else first_days_ago)
    relationship.previous_attempts = count
    return f


def unregistered_device(f: Features, approved_days: int = 0, other_devices: int = 1, ip_known: bool = False):
    device = f.device
    device.device_id = "dvc-new"
    device.approved_days = approved_days
    device.approved_devices_count = other_devices + (1 if approved_days else 0)
    device.first_approved_at = MOMENT - timedelta(days=1) if approved_days else None
    device.last_used_at = MOMENT - timedelta(days=1) if approved_days else None
    device.device_previous_uses = approved_days
    if not ip_known:
        device.ip_previous_uses = 0
    return f


def inflow_24h(f: Features, amount: int, new_counterparties: int, count: int = None) -> Features:
    inflow = f.payer.last_24h.inflow
    inflow.amount = amount
    inflow.count = count if count is not None else new_counterparties
    inflow.distinct_counterparties = inflow.count
    inflow.new_counterparties = new_counterparties
    return f


def outflow_24h(f: Features, amount: int, count: int, new_counterparties: int = 0, in_period: bool = True) -> Features:
    for window in (f.payer.last_24h, f.payer.current_period) if in_period else (f.payer.last_24h,):
        window.outflow = FlowSideFeatures(
            amount=amount,
            count=count,
            distinct_counterparties=count,
            new_counterparties=new_counterparties,
            repeated_counterparties=0,
        )
    f.velocity.attempts_last_24h = count
    f.velocity.attempts_last_1h = count
    return f


def at_night(f: Features, hour: int = 23) -> Features:
    moment = MOMENT.replace(hour=hour)
    f.transaction.transaction_date = moment
    f.transaction.local_hour = hour
    f.transaction.period = "night"
    f.payer.current_period.kind = "night"
    f.payer.current_period.limit = f.payer.nightly_limit
    return f


def dict_answer(f: Features, account: list = None, owner: list = None) -> Features:
    f.destination.dict = DictFeatures(
        status=DICT_OK,
        response={"account": {"fraud_markers": account or []}, "owner": {"fraud_markers": owner or []}},
        fetched_at=MOMENT,
    )
    return f


def payer_dict(f: Features, account: list = None, owner: list = None) -> Features:
    """O DICT da conta que envia (vem do resumo diário)."""
    f.payer.dict = DictFeatures(
        status=DICT_OK,
        response={"account": {"fraud_markers": account or []}, "owner": {"fraud_markers": owner or []}},
        fetched_at=MOMENT,
    )
    return f


def marker(marker_type: str, days_ago: int) -> dict:
    return {"type": marker_type, "created_at": (MOMENT - timedelta(days=days_ago)).isoformat()}


def internal_destination(f: Features, age_days: int, balance: int = 100000) -> InternalAccountFeatures:
    """Destino nosso: devolve a conta para o cenário ajustar o fluxo dela."""
    account = internal_account(balance=balance)
    account.account_key = "a0000000-0000-4000-8000-000000000099"
    account.account_age_days = age_days
    f.destination.is_internal = True
    f.destination.participant = "88888888"
    f.destination.account = account
    f.destination.account_age_days = age_days
    return account


def settle(f: Features) -> Features:
    """Fecha as contas do cenário: saldo no início das 24h e razões da janela, a partir do saldo de agora."""
    window = f.payer.last_24h
    window.balance_at_start = max(0, f.payer.balance - window.inflow.amount + window.outflow.amount)
    window.pass_through_rate = window.outflow.amount / window.inflow.amount if window.inflow.amount else None
    base = window.balance_at_start + window.inflow.amount
    window.exit_ratio = window.outflow.amount / base if base else None

    amount = f.transaction.amount
    f.transaction.ratio_to_balance = amount / f.payer.balance if f.payer.balance else None
    return f
