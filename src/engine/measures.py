"""Features → medidas derivadas (4.2, seção 4.1).

Medidas são números, não decisões: o p90 combinado com o perfil padrão, a
fatia do saldo, a razão de saída com este Pix, se o aparelho é cadastrado,
as marcações do DICT com idade... Os sinais (src/engine/signals/) leem
daqui. Tudo puro: nada de banco, rede ou relógio — o "agora" é a data do
próprio Pix.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from engine import params
from engine.features import DICT_FALLBACK, DICT_OK, DictFeatures, Features, InternalAccountFeatures

PJ = "PJ"


@dataclass
class Measures:
    amount: int                         # centavos
    amount_reais: float
    is_night: bool
    n_out: float                        # Pix de saída na janela de 30 dias
    p90_blend: float
    amount_ratio: float                 # valor / p90 combinado
    balance_share: Optional[float]      # valor / saldo
    daily_count_blend: float
    attempts_24h_with_pix: int
    exit_ratio_with_pix: Optional[float]
    pass_through_with_pix: Optional[float]
    payer_inflow_jump: Optional[float]
    payer_dormant: bool
    first_payment: bool
    relationship_age_days: Optional[float]
    escalating: bool
    recurring: bool
    two_way: bool
    same_owner: bool
    new_payees_period: int
    destination_age_days: int
    destination_is_pj: bool
    fan_in: int
    fan_in_factor: int
    destination_inflow_jump: Optional[float]
    destination_dormant: bool
    destination_pass_through: Optional[float]
    device_registered: bool
    cold_start: bool
    speed_kmh: Optional[float]
    dict_recent: bool                   # DICT respondeu agora ou fallback de até 24h
    dict_markers: List[Tuple[str, float]] = field(default_factory=list)  # (tipo, idade em dias)
    payer_dict_markers: List[Tuple[str, float]] = field(default_factory=list)  # as do próprio pagador

    @property
    def payer_dict_marked(self) -> bool:
        """O pagador tem marcação de laranja ou golpista ainda válida (5 anos) no DICT."""
        return any(
            t in params.DICT_HARD_TYPES and age <= params.DICT_VALID_DAYS for t, age in self.payer_dict_markers
        )


def measure(f: Features) -> Measures:
    payer = f.payer
    baseline = payer.baseline
    relationship = f.relationship
    destination = f.destination
    amount = f.transaction.amount
    moment = f.transaction.transaction_date

    n_out = _n_out(payer)
    p90_blend = _p90_blend(baseline.p90_out_amount, n_out)
    daily_count_blend = (n_out * (baseline.avg_daily_out_count or 0) + params.K_PRIOR * params.DAILY_COUNT_PRIOR) / (
        n_out + params.K_PRIOR
    )

    last_24h = payer.last_24h
    out_with_pix = last_24h.outflow.amount + amount
    exit_base = last_24h.balance_at_start + last_24h.inflow.amount

    first_payment = relationship.previous_out_count == 0 or (
        relationship.first_out_at is not None
        and moment - relationship.first_out_at < timedelta(hours=params.WINDOW_24H_HOURS)
    )

    relationship_age_days = None
    if relationship.first_out_at is not None:
        relationship_age_days = (moment - relationship.first_out_at).total_seconds() / 86400

    escalating = (
        relationship.previous_out_count >= 2
        and relationship_age_days is not None
        and relationship_age_days < 180
        and relationship.max_previous_out_amount is not None
        and amount > relationship.max_previous_out_amount
    )

    average_paid = None
    if relationship.previous_out_count > 0:
        average_paid = relationship.previous_out_amount / relationship.previous_out_count

    recurring = (
        relationship.previous_out_count >= 3
        and relationship_age_days is not None
        and relationship_age_days >= 30
        and not escalating
        and average_paid is not None
        and amount <= 1.5 * average_paid
        and destination.account_age_days >= 180
    )

    two_way = (
        relationship.previous_in_amount >= 5_000
        and relationship.first_in_at is not None
        and moment - relationship.first_in_at >= timedelta(days=30)
    )

    new_payees_period = payer.current_period.outflow.new_counterparties + (
        1 if relationship.previous_out_count == 0 else 0
    )

    destination_account = destination.account
    destination_pass_through = None
    if destination_account is not None:
        destination_pass_through = destination_account.last_24h.pass_through_rate

    return Measures(
        amount=amount,
        amount_reais=amount / 100,
        is_night=f.transaction.period == "night",
        n_out=n_out,
        p90_blend=p90_blend,
        amount_ratio=amount / p90_blend,
        balance_share=_ratio(amount, payer.balance),
        daily_count_blend=daily_count_blend,
        attempts_24h_with_pix=f.velocity.attempts_last_24h + 1,
        exit_ratio_with_pix=_ratio(out_with_pix, exit_base),
        pass_through_with_pix=_ratio(out_with_pix, last_24h.inflow.amount),
        payer_inflow_jump=inflow_jump(payer),
        payer_dormant=is_dormant(payer),
        first_payment=first_payment,
        relationship_age_days=relationship_age_days,
        escalating=escalating,
        recurring=recurring,
        two_way=two_way,
        same_owner=relationship.same_owner,
        new_payees_period=new_payees_period,
        destination_age_days=destination.account_age_days,
        destination_is_pj=destination.document_type == PJ,
        fan_in=destination.history.new_payers_7d,
        fan_in_factor=params.PJ_FAN_IN_FACTOR if destination.document_type == PJ else 1,
        destination_inflow_jump=inflow_jump(destination_account) if destination_account is not None else None,
        destination_dormant=is_dormant(destination_account) if destination_account is not None else False,
        destination_pass_through=destination_pass_through,
        device_registered=device_is_known(f),
        cold_start=is_cold_start(f),
        speed_kmh=_speed(f.device.distance_from_last_km, f.device.minutes_since_last_location),
        dict_recent=dict_is_recent(f),
        dict_markers=dict_markers(f.destination.dict, moment),
        payer_dict_markers=dict_markers(payer.dict, moment),
    )


# ── Perfil do pagador ────────────────────────────────────────────


def _n_out(account: InternalAccountFeatures) -> float:
    baseline = account.baseline
    return (baseline.avg_daily_out_count or 0) * baseline.history_days


def _p90_blend(own_p90: Optional[int], n_out: float) -> float:
    """O p90 de saída puxado para o padrão quando há pouco histórico (média geométrica ponderada)."""
    if not own_p90 or own_p90 <= 0 or n_out <= 0:
        return float(params.P90_PRIOR)

    k = params.K_PRIOR
    return math.exp((n_out * math.log(own_p90) + k * math.log(params.P90_PRIOR)) / (n_out + k))


def inflow_30d(account: InternalAccountFeatures) -> float:
    baseline = account.baseline
    return (baseline.avg_in_amount or 0) * (baseline.avg_daily_in_count or 0) * baseline.history_days


def inflow_jump(account: InternalAccountFeatures) -> Optional[float]:
    """Quantos "meses de entrada" chegaram em 24h. Só com 30 dias de histórico."""
    if account.baseline.history_days < params.FULL_HISTORY_DAYS:
        return None

    return account.last_24h.inflow.amount / max(inflow_30d(account), params.INFLOW_JUMP_FLOOR)


def is_dormant(account: InternalAccountFeatures) -> bool:
    baseline = account.baseline
    daily = (baseline.avg_daily_out_count or 0) + (baseline.avg_daily_in_count or 0)

    return baseline.history_days >= params.FULL_HISTORY_DAYS and daily <= 0.1 and account.account_age_days >= 180


# ── Aparelho ─────────────────────────────────────────────────────


def device_is_registered(
    approved_days: int, first_approved_at: Optional[datetime], last_used_at: Optional[datetime], moment: datetime
) -> bool:
    """Aparelho cadastrado (IN BCB 491, art. 7º): Pix aprovado em ≥ 3 dias distintos,
    o primeiro há ≥ 7 dias, e usado nos últimos 12 meses.

    É também o que a API usa para somar o que saiu hoje de aparelhos não
    cadastrados (`unregistered_amount_today`).
    """
    if approved_days < params.DEVICE_KNOWN_DAYS or first_approved_at is None:
        return False

    if moment - first_approved_at < timedelta(days=params.DEVICE_KNOWN_MIN_AGE_DAYS):
        return False

    return last_used_at is not None and moment - last_used_at <= timedelta(days=params.DEVICE_EXPIRY_DAYS)


def is_cold_start(f: Features) -> bool:
    """Conta de até 7 dias em que nenhum OUTRO aparelho tem Pix aprovado: é o aparelho do onboarding."""
    device = f.device
    other_approved_devices = device.approved_devices_count - (1 if device.approved_days > 0 else 0)

    return f.payer.account_age_days <= params.COLD_START_ACCOUNT_DAYS and other_approved_devices <= 0


def device_is_known(f: Features) -> bool:
    device = f.device
    registered = device_is_registered(
        device.approved_days, device.first_approved_at, device.last_used_at, f.transaction.transaction_date
    )

    return registered or is_cold_start(f)


def _speed(distance_km: Optional[float], minutes: Optional[float]) -> Optional[float]:
    if distance_km is None or minutes is None:
        return None

    if minutes <= 0:
        return math.inf if distance_km > 0 else 0.0

    return distance_km / (minutes / 60)


# ── DICT ─────────────────────────────────────────────────────────


def dict_is_recent(f: Features) -> bool:
    """O DICT respondeu agora, ou o fallback tem no máximo 24h."""
    consult = f.destination.dict
    if consult is None:
        return False

    if consult.status == DICT_OK:
        return True

    if consult.status == DICT_FALLBACK and consult.fetched_at is not None:
        return f.transaction.transaction_date - consult.fetched_at <= timedelta(hours=params.DICT_STALE_HOURS)

    return False


def dict_markers(consult: Optional[DictFeatures], moment: datetime) -> List[Tuple[str, float]]:
    """(tipo, idade em dias) de cada marcação da conta e do dono — do destino ou do pagador.

    Lê com cuidado: o formato vem de fora, e um campo faltando não pode
    derrubar a decisão. Marcação sem data conta como recente. Um fallback
    velho ainda conta (não esquecemos uma marcação), mas não tira o Pix do
    "sem DICT recente".
    """
    if consult is None or not isinstance(consult.response, dict):
        return []

    markers = []

    for subject in ("account", "owner"):
        items = (consult.response.get(subject) or {}).get("fraud_markers") or []
        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue

            markers.append((str(item.get("type") or "UNKNOWN"), _age_days(item.get("created_at"), moment)))

    return markers


def _age_days(raw, moment: datetime) -> float:
    if not isinstance(raw, str):
        return 0.0

    try:
        created_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return 0.0

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=moment.tzinfo)

    return max(0.0, (moment - created_at).total_seconds() / 86400)


def _ratio(numerator, denominator) -> Optional[float]:
    if denominator is None or denominator <= 0:
        return None

    return numerator / denominator
