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
        ),
        velocity=VelocityFeatures(
            attempts_last_1h=0,
            attempts_last_24h=1,
            attempts_current_period=0,
            seconds_since_last_attempt=36000.0,
        ),
    )
