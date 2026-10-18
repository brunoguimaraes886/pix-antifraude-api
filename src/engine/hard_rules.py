"""Regras duras (4.2, seção 3): não passam pelo score.

São obrigações (do BC ou já decididas) ou situações sem margem de dúvida.
Todas rodam; vale a mais severa. As que rejeitam dão `rejected`; as que só
põem um piso dão `two_factor_required`, e nenhuma camada depois desce
abaixo dele.

Duas fases: as que não dependem do DICT rodam antes da consulta (se já
rejeitam, o DICT nem é consultado); as do DICT rodam depois.
"""

from typing import Callable, List, Optional, Tuple

from engine import params
from engine.features import Features
from engine.measures import Measures
from engine.reasons import (
    BETTING_DESTINATION,
    DESTINATION_ACCOUNT_BLOCKED,
    DICT_FRAUD_MARKER,
    DICT_MARKER,
    DICT_UNAVAILABLE,
    LIMIT_EXCEEDED,
    NEW_DEVICE_LIMIT,
    NEW_DEVICE_STRUCTURING,
    REPEAT_AFTER_FRAUD_REJECTION,
    SANCTIONED_PARTY,
    Reason,
)
from engine.result import REJECTED, TWO_FACTOR_REQUIRED

Outcome = Optional[Tuple[str, Reason]]
HardRule = Callable[[Features, Measures], Outcome]

CSNU = "csnu"
BETS = "bets"
PF = "PF"


# ── Antes do DICT ────────────────────────────────────────────────


def sanctioned_party(f: Features, m: Measures) -> Outcome:
    """Sanções do CSNU: obrigatório para o pagador (Regulamento, art. 38, V) e,
    para o destino, por inferência (Lei 13.810, art. 8º)."""
    if f.payer.restricted_list == CSNU or f.destination.restricted_list == CSNU:
        return REJECTED, SANCTIONED_PARTY
    return None


def betting_destination(f: Features, m: Measures) -> Outcome:
    """Pix destinado a apostas de quota fixa (Regulamento, art. 32, XI). Só o lado do destino."""
    if f.destination.restricted_list == BETS:
        return REJECTED, BETTING_DESTINATION
    return None


def effective_limit(f: Features, m: Measures) -> int:
    """O limite noturno do BC vale só entre pessoas físicas distintas (Res. 142, art. 2º;
    IN 512, art. 3º, §§ 7º e 8º). Nos outros casos, mesmo à noite, vale o diurno."""
    night_limit_applies = (
        m.is_night
        and f.payer.customer.document_type == PF
        and f.destination.document_type == PF
        and not m.same_owner
    )

    return f.payer.nightly_limit if night_limit_applies else f.payer.daily_limit


def limit_exceeded(f: Features, m: Measures) -> Outcome:
    """"Passou do limite → bloqueia na hora". O limite é do período: o que já saiu soma."""
    if f.payer.current_period.outflow.amount + m.amount > effective_limit(f, m):
        return REJECTED, LIMIT_EXCEEDED
    return None


def repeat_after_fraud_rejection(f: Features, m: Measures) -> Outcome:
    """Destino já rejeitado por suspeita para este cliente em 24h: "tente um valor menor" é roteiro de golpe."""
    if f.relationship.fraud_rejections_24h >= 1:
        return REJECTED, REPEAT_AFTER_FRAUD_REJECTION
    return None


def destination_account_blocked(f: Features, m: Measures) -> Outcome:
    account = f.destination.account
    if account is not None and account.is_blocked:
        return REJECTED, DESTINATION_ACCOUNT_BLOCKED
    return None


def new_device_limit(f: Features, m: Measures) -> Outcome:
    """IN BCB 491, art. 9º: R$ 200 por Pix e R$ 1.000 por dia somando todos os aparelhos não cadastrados."""
    if m.device_registered:
        return None

    day_total = f.payer.unregistered_amount_today + m.amount
    if m.amount > params.NEW_DEVICE_MAX_PIX or day_total > params.NEW_DEVICE_MAX_DAY:
        return TWO_FACTOR_REQUIRED, NEW_DEVICE_LIMIT

    return None


def new_device_structuring(f: Features, m: Measures) -> Outcome:
    """Fracionamento logo abaixo de R$ 200 para escapar da regra acima, mesmo trocando de destino."""
    if m.device_registered:
        return None

    if params.NEAR_LIMIT_MIN <= m.amount <= params.NEW_DEVICE_MAX_PIX and f.payer.unregistered_near_limit_24h >= 1:
        return TWO_FACTOR_REQUIRED, NEW_DEVICE_STRUCTURING

    return None


PRE_DICT_RULES: List[HardRule] = [
    sanctioned_party,
    betting_destination,
    limit_exceeded,
    repeat_after_fraud_rejection,
    destination_account_blocked,
    new_device_limit,
    new_device_structuring,
]


# ── Depois do DICT ───────────────────────────────────────────────


def _recent_hard_marker(m: Measures) -> bool:
    return any(t in params.DICT_HARD_TYPES and age <= params.DICT_HARD_DAYS for t, age in m.dict_markers)


def _valid_floor_marker(m: Measures) -> bool:
    return any(t in params.DICT_FLOOR_TYPES and age <= params.DICT_VALID_DAYS for t, age in m.dict_markers)


def dict_fraud_marker(f: Features, m: Measures) -> Outcome:
    """Critério nosso de fundada suspeita pelo DICT (Res. 142, art. 2º-A): marcação de laranja ou
    golpista em 12 meses E um reforço (conta nova, fan-in ou rejeição por suspeita com outro cliente).

    Marcação de outro PSP sozinha não obriga a rejeitar: o reforço evita punir
    CPF com marcação antiga e conta legítima.
    """
    if not _recent_hard_marker(m):
        return None

    reinforced = (
        m.destination_age_days < params.DICT_REINFORCEMENT_ACCOUNT_DAYS
        or m.fan_in >= params.DICT_REINFORCEMENT_FAN_IN
        or f.destination.history.fraud_rejected_payers_90d >= 1
    )

    if reinforced:
        return REJECTED, DICT_FRAUD_MARKER
    return None


def dict_marker(f: Features, m: Measures) -> Outcome:
    """Qualquer marcação válida que não virou rejeição: suspeita, não fundada suspeita.

    `APPLICATION_FRAUD` no CPF aponta a vítima de roubo de identidade, por isso
    nunca rejeita sozinha.
    """
    if _valid_floor_marker(m) and dict_fraud_marker(f, m) is None:
        return TWO_FACTOR_REQUIRED, DICT_MARKER
    return None


def dict_unavailable(f: Features, m: Measures) -> Outcome:
    """Sem DICT recente, destino de outro banco e relação nova: a dúvida vira fricção, não bloqueio."""
    if not m.dict_recent and not f.destination.is_internal and f.relationship.previous_out_count == 0:
        return TWO_FACTOR_REQUIRED, DICT_UNAVAILABLE
    return None


DICT_RULES: List[HardRule] = [dict_fraud_marker, dict_marker, dict_unavailable]


def run(rules: List[HardRule], f: Features, m: Measures) -> List[Tuple[str, Reason]]:
    outcomes = []
    for rule in rules:
        outcome = rule(f, m)
        if outcome is not None:
            outcomes.append(outcome)
    return outcomes
