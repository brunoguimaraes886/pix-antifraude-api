"""Cenário em linguagem de negócio (calibration/schema.md) → `Features` do motor.

Os cenários são escritos por agentes que não conhecem o motor, num formato
próprio (reais, campos com nome de negócio). Aqui eles viram o `Features`
que a API montaria. O DICT vem pronto no cenário: não há consulta.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from engine.features import (
    DICT_OK,
    DICT_UNAVAILABLE,
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
DAY = datetime(2026, 10, 14, tzinfo=SAO_PAULO)   # uma quarta-feira

KNOWN_RELATIONSHIP = {
    "previous_payments": 3,
    "previous_total": 300.0,
    "largest_previous": 120.0,
    "first_payment_days_ago": 60,
    "last_payment_days_ago": 5,
}


def cents(value) -> Optional[int]:
    return None if value is None else int(round(float(value) * 100))


def _get(block: Optional[dict], key: str, default):
    """O valor do cenário; o padrão só quando o campo não aparece (null explícito vale null)."""
    return (block or {}).get(key, default)


def _side(amount, count, new) -> FlowSideFeatures:
    count = int(count or 0)
    return FlowSideFeatures(
        amount=cents(amount or 0),
        count=count,
        distinct_counterparties=count,
        new_counterparties=int(new or 0),
        repeated_counterparties=0,
    )


def _window(start, end, balance_now, inflow, outflow) -> dict:
    balance_at_start = max(0, balance_now - inflow.amount + outflow.amount)
    base = balance_at_start + inflow.amount
    return dict(
        start=start,
        end=end,
        balance_at_start=balance_at_start,
        inflow=inflow,
        outflow=outflow,
        pass_through_rate=outflow.amount / inflow.amount if inflow.amount else None,
        exit_ratio=outflow.amount / base if base else None,
    )


def _periods(moment: datetime, is_night: bool):
    if is_night:
        start = moment.replace(hour=20, minute=0) if moment.hour >= 20 else (moment - timedelta(days=1)).replace(hour=20, minute=0)
        return start, start - timedelta(hours=14), "night", "day"
    start = moment.replace(hour=6, minute=0)
    return start, start - timedelta(hours=10), "day", "night"


def _account(
    data: dict,
    moment: datetime,
    is_night: bool,
    account_key: str,
    inflow: FlowSideFeatures,
    outflow: FlowSideFeatures,
    period_outflow: FlowSideFeatures,
) -> InternalAccountFeatures:
    balance = cents(_get(data, "balance", 5000.0))
    daily_limit = cents(_get(data, "daily_limit", 10000.0))
    nightly_limit = cents(_get(data, "nightly_limit", 1000.0))

    current_start, previous_start, kind, previous_kind = _periods(moment, is_night)
    empty = _side(0, 0, 0)
    last_24h = _window(moment - timedelta(hours=24), moment, balance, inflow, outflow)
    current = _window(current_start, moment, balance, empty, period_outflow)
    previous = _window(previous_start, current_start, balance, empty, empty)

    return InternalAccountFeatures(
        account_key=account_key,
        customer=CustomerFeatures(
            document_type=_get(data, "type", "PF"),
            age_years=int(_get(data, "age_years", 41)),
        ),
        account_age_days=int(_get(data, "account_age_days", 600)),
        balance=balance,
        daily_limit=daily_limit,
        nightly_limit=nightly_limit,
        is_blocked=bool(_get(data, "blocked", False)),
        baseline=BaselineFeatures(
            baseline_date=moment.date(),
            history_days=int(_get(data, "history_days", 30)),
            avg_out_amount=cents(_get(data, "avg_pix_out", 150.0)),
            p90_out_amount=cents(_get(data, "typical_large_pix", 400.0)),
            avg_in_amount=cents(_get(data, "avg_pix_in", 2000.0)),
            p90_in_amount=None,
            avg_daily_out_count=float(_get(data, "pix_out_per_day", 0.8)),
            avg_daily_in_count=float(_get(data, "pix_in_per_day", 0.2)),
            account_block_count=int(_get(data, "past_account_blocks", 0)),
            rejected_pix_out_count=int(_get(data, "past_rejected_pix", 0)),
            rejected_pix_in_count=int(_get(data, "past_rejected_pix_in", 0)),
            night_out_share=_get(data, "night_share", 0.2),
        ),
        last_24h=FlowWindowFeatures(**last_24h),
        current_period=PeriodFeatures(
            **current, kind=kind, is_current=True, limit=nightly_limit if is_night else daily_limit
        ),
        previous_period=PeriodFeatures(
            **previous, kind=previous_kind, is_current=False, limit=daily_limit if is_night else nightly_limit
        ),
        restricted_list=_get(data, "restricted", None),
    )


def _days_ago(moment: datetime, days) -> Optional[datetime]:
    return None if days is None else moment - timedelta(days=float(days))


def to_features(scenario: dict) -> Features:
    pix = scenario.get("pix") or {}
    payer = scenario.get("payer") or {}
    flow = scenario.get("flow_24h") or {}
    device = scenario.get("device") or {}
    velocity = scenario.get("velocity") or {}
    destination = scenario.get("destination") or {}
    relationship = scenario.get("relationship")
    if relationship is None:
        relationship = KNOWN_RELATIONSHIP

    hour = int(pix.get("hour", 14)) % 24
    moment = DAY.replace(hour=hour, minute=30)
    is_night = hour >= 20 or hour < 6
    amount = cents(pix.get("amount", 150.0))

    inflow = _side(flow.get("inflow_amount", 0), flow.get("inflow_count", 0), flow.get("inflow_new_senders", 0))
    outflow = _side(flow.get("outflow_amount", 0), flow.get("outflow_count", 0), flow.get("outflow_new_recipients", 0))
    payer_account = _account(payer, moment, is_night, "payer", inflow, outflow, outflow)

    # ── Aparelho ───────────────────────────────────────────────────
    registered = bool(device.get("registered", True))
    others = int(device.get("other_registered_devices", 0 if registered else 1))
    has_geo = bool(device.get("has_geolocation", True))
    device_features = DeviceFeatures(
        device_id="dvc",
        channel="app",
        ip="198.51.100.23",
        device_previous_uses=40 if registered else 0,
        device_previous_approved_uses=40 if registered else 0,
        device_first_seen_at=moment - timedelta(days=200) if registered else None,
        ip_previous_uses=10 if device.get("ip_seen_before", registered) else 0,
        distinct_devices_last_30d=1 + (0 if registered else 1),
        latitude=-23.56 if has_geo else None,
        longitude=-46.65 if has_geo else None,
        distance_from_last_km=device.get("distance_from_last_km", 0.4 if has_geo else None),
        minutes_since_last_location=device.get("minutes_since_last_location", 600.0 if has_geo else None),
        approved_devices_count=others + (1 if registered else 0),
        approved_days=40 if registered else 0,
        first_approved_at=moment - timedelta(days=200) if registered else None,
        last_used_at=moment - timedelta(days=1) if registered else None,
        other_accounts_last_30d=int(device.get("other_accounts_on_device_30d", 0)),
        channel_previous_uses=40 if device.get("channel_used_before", True) else 0,
    )
    payer_account.unregistered_amount_today = cents(device.get("unregistered_sent_today", 0))
    payer_account.unregistered_near_limit_24h = int(device.get("near_200_from_unregistered_24h", 0))

    # ── Destino ────────────────────────────────────────────────────
    internal = destination.get("bank", "other") == "same"
    destination_account = None
    if internal:
        data = dict(destination.get("internal") or {})
        data.setdefault("type", destination.get("type", "PF"))
        data.setdefault("account_age_days", destination.get("account_age_days", 900))
        data.setdefault("balance", 1000.0)
        dest_in = _side(
            data.get("inflow_24h_amount", 0), data.get("inflow_24h_count", 0), data.get("inflow_24h_new_senders", 0)
        )
        dest_out_amount = data.get("outflow_24h_amount", 0)
        dest_out = _side(dest_out_amount, 1 if dest_out_amount else 0, 0)
        destination_account = _account(data, moment, is_night, "destination", dest_in, dest_out, dest_out)

    dict_data = destination.get("dict") or {}
    if dict_data.get("available", True):
        response = {"account": {"fraud_markers": []}, "owner": {"fraud_markers": []}}
        for item in dict_data.get("markers") or []:
            subject = "owner" if item.get("on") == "owner" else "account"
            created = moment - timedelta(days=float(item.get("days_ago", 0)))
            response[subject]["fraud_markers"].append({"type": item.get("type", "OTHER"), "created_at": created.isoformat()})
        dict_features = DictFeatures(status=DICT_OK, response=response, fetched_at=moment)
    else:
        dict_features = DictFeatures(status=DICT_UNAVAILABLE, response=None, fetched_at=None)

    previous = int(relationship.get("previous_payments") or 0)
    destination_features = DestinationFeatures(
        is_internal=internal,
        participant="88888888" if internal else "60701190",
        document_type=destination.get("type", "PF"),
        account_age_days=int(destination.get("account_age_days", 900)),
        account=destination_account,
        history=DestinationHistoryFeatures(
            total_count=previous,
            approved_count=previous,
            two_factor_count=0,
            rejected_count=0,
            approved_amount=cents(relationship.get("previous_total") or 0),
            distinct_payers=1 if previous else 0,
            first_seen_at=None,
            last_seen_at=None,
            last_24h_count=0,
            last_24h_distinct_payers=0,
            last_24h_approved_amount=0,
            new_payers_7d=int(destination.get("other_clients_first_paid_7d", 0)),
            fraud_rejected_payers_90d=int(destination.get("other_clients_rejected_90d", 0)),
        ),
        dict=dict_features,
        restricted_list=destination.get("restricted"),
    )
    if destination_account is not None:
        destination_account.is_blocked = bool((destination.get("internal") or {}).get("blocked", False))

    # ── Relação ────────────────────────────────────────────────────
    relationship_features = RelationshipFeatures(
        previous_out_count=previous,
        previous_out_amount=cents(relationship.get("previous_total") or 0),
        max_previous_out_amount=cents(relationship.get("largest_previous")) if previous else None,
        first_out_at=_days_ago(moment, relationship.get("first_payment_days_ago")) if previous else None,
        last_out_at=_days_ago(moment, relationship.get("last_payment_days_ago")) if previous else None,
        out_days_last_30d=0,
        previous_in_count=1 if relationship.get("received_from_destination_total") else 0,
        previous_attempts=previous,
        same_owner=bool(destination.get("same_owner", False)),
        previous_in_amount=cents(relationship.get("received_from_destination_total") or 0),
        first_in_at=_days_ago(moment, relationship.get("first_received_days_ago")),
        attempts_to_destination_24h=int(relationship.get("attempts_to_destination_24h") or 0),
        last_attempt_amount=cents(relationship.get("last_attempt_amount")),
        blocked_attempts_24h=int(relationship.get("blocked_attempts_24h") or 0),
        fraud_rejections_24h=int(relationship.get("fraud_rejections_24h") or 0),
        matching_recent_inflow=bool(flow.get("matching_inflow_from_stranger", False)),
    )

    balance = payer_account.balance
    avg_out = payer_account.baseline.avg_out_amount
    p90_out = payer_account.baseline.p90_out_amount

    return Features(
        transaction=TransactionFeatures(
            pix_id=str(scenario.get("id", "scenario")),
            amount=amount,
            transaction_date=moment,
            local_hour=hour,
            weekday=moment.weekday(),
            period="night" if is_night else "day",
            ratio_to_balance=amount / balance if balance else None,
            ratio_to_avg_out=amount / avg_out if avg_out else None,
            ratio_to_p90_out=amount / p90_out if p90_out else None,
        ),
        payer=payer_account,
        destination=destination_features,
        relationship=relationship_features,
        device=device_features,
        velocity=VelocityFeatures(
            attempts_last_1h=int(velocity.get("attempts_1h", 0)),
            attempts_last_24h=int(velocity.get("attempts_24h", max(1, outflow.count))),
            attempts_current_period=int(velocity.get("attempts_1h", 0)),
            seconds_since_last_attempt=velocity.get("seconds_since_last_attempt", 36000.0),
        ),
    )

