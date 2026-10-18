"""Destino: quem recebe é confiável? (4.2, seção 5.5 — teto 80, ρ = 0,1)

ρ baixo: confirmar quem paga não muda quem recebe.
"""

from typing import Optional

from engine import params
from engine.evidence import Evidence, evidence
from engine.features import Features
from engine.measures import Measures
from engine.params import DESTINATION


def dict_history(f: Features, m: Measures) -> Optional[Evidence]:
    """Reputação compartilhada entre os bancos, com peso que cai com o tempo. Vale a marcação mais forte."""
    best = 0
    for marker_type, age_days in m.dict_markers:
        if age_days > params.DICT_VALID_DAYS:
            continue

        recent = age_days <= params.DICT_HARD_DAYS
        if marker_type in params.DICT_FLOOR_TYPES:
            points = 40 if recent else 20
        else:
            points = 15 if recent else 5

        best = max(best, points)

    if best:
        return evidence("dict_history", DESTINATION, best)
    return None


def new_destination_account(f: Features, m: Measures) -> Optional[Evidence]:
    """Fator que o BC manda olhar (art. 39-B). Conta própria nova já conta em `own_account_new`."""
    if m.same_owner:
        return None

    for maximum, points in ((7, 40), (30, 30), (90, 15), (180, 5)):
        if m.destination_age_days < maximum:
            return evidence("new_destination_account", DESTINATION, points)

    return None


def destination_fan_in(f: Features, m: Measures) -> Optional[Evidence]:
    """Várias vítimas pagando a mesma conta: o sinal de laranja que se vê até em conta de outro banco."""
    for minimum, points in ((8, 40), (4, 25), (2, 10)):
        if m.fan_in >= minimum * m.fan_in_factor:
            return evidence("destination_fan_in", DESTINATION, points)
    return None


def destination_rejected_before(f: Features, m: Measures) -> Optional[Evidence]:
    """O motor já viu fundada suspeita neste destino com OUTROS clientes, em 90 dias."""
    rejected = f.destination.history.fraud_rejected_payers_90d

    if rejected >= 3:
        return evidence("destination_rejected_before", DESTINATION, 50)
    if rejected == 2:
        return evidence("destination_rejected_before", DESTINATION, 40)
    if rejected == 1:
        return evidence("destination_rejected_before", DESTINATION, 25)
    return None


def destination_pass_through(f: Features, m: Measures) -> Optional[Evidence]:
    """Destino nosso que não acumula: repassa ≥ 80% do que entrou nas 24h."""
    account = f.destination.account
    if account is None or m.destination_pass_through is None:
        return None

    inflow = account.last_24h.inflow
    if m.destination_pass_through < 0.8 or inflow.amount < 50_000:
        return None

    if inflow.new_counterparties >= 3:
        return evidence("destination_pass_through", DESTINATION, 30)

    return evidence("destination_pass_through", DESTINATION, 20)


def destination_inflow_jump(f: Features, m: Measures) -> Optional[Evidence]:
    """"Movimentação incompatível com a capacidade financeira", contra o próprio histórico."""
    jump = m.destination_inflow_jump
    if jump is None:
        return None

    if jump >= 10:
        return evidence("destination_inflow_jump", DESTINATION, 30)
    if jump >= 3:
        return evidence("destination_inflow_jump", DESTINATION, 15)
    return None


def destination_dormant_awakened(f: Features, m: Measures) -> Optional[Evidence]:
    account = f.destination.account
    if account is not None and m.destination_dormant and account.last_24h.inflow.count >= 3:
        return evidence("destination_dormant_awakened", DESTINATION, 20)
    return None


def destination_block_history(f: Features, m: Measures) -> Optional[Evidence]:
    account = f.destination.account
    if account is None:
        return None

    points = min(20, 10 * account.baseline.account_block_count)
    if account.baseline.rejected_pix_in_count >= 1:
        points = points + 15

    if points:
        return evidence("destination_block_history", DESTINATION, points)
    return None


SIGNALS = (
    dict_history,
    new_destination_account,
    destination_fan_in,
    destination_rejected_before,
    destination_pass_through,
    destination_inflow_jump,
    destination_dormant_awakened,
    destination_block_history,
)
