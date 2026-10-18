"""Ritmo e acumulado (4.2, seção 5.3 — teto 40, ρ = 0,4).

Velocidade nunca é teto (o Regulamento proíbe limitar o número de
transações, art. 37-A): ritmo e tentativas só entram como pontos.
"""

from typing import Optional

from engine.evidence import Evidence, evidence
from engine.features import Features
from engine.measures import Measures
from engine.params import VELOCITY


def velocity_spike(f: Features, m: Measures) -> Optional[Evidence]:
    attempts = m.attempts_24h_with_pix

    if attempts >= 6 * m.daily_count_blend and attempts >= 8:
        return evidence("velocity_spike", VELOCITY, 20)

    if attempts >= 3 * m.daily_count_blend and attempts >= 5:
        return evidence("velocity_spike", VELOCITY, 10)

    return None


def new_payee_burst(f: Features, m: Measures) -> Optional[Evidence]:
    if m.new_payees_period >= 3:
        return evidence("new_payee_burst", VELOCITY, 15)

    if m.new_payees_period == 2:
        return evidence("new_payee_burst", VELOCITY, 8)

    return None


def high_outflow_ratio(f: Features, m: Measures) -> Optional[Evidence]:
    """O roubo com "intervalo calculado": olha o acumulado das 24h, não a velocidade.

    Só pontua se já houve saída antes; senão repetiria o `balance_drain`.
    """
    if f.payer.last_24h.outflow.amount <= 0 or m.exit_ratio_with_pix is None:
        return None

    if m.exit_ratio_with_pix >= 0.9:
        return evidence("high_outflow_ratio", VELOCITY, 18)

    if m.exit_ratio_with_pix >= 0.7:
        return evidence("high_outflow_ratio", VELOCITY, 10)

    return None


def retry_after_block(f: Features, m: Measures) -> Optional[Evidence]:
    """"Faz de novo que agora vai": tentar de novo depois de um 2FA ou rejeição."""
    if f.relationship.blocked_attempts_24h >= 1:
        return evidence("retry_after_block", VELOCITY, 20)
    return None


def split_payments(f: Features, m: Measures) -> Optional[Evidence]:
    """3º Pix para o mesmo destino em 24h, com valor a ±10% do anterior."""
    relationship = f.relationship
    last = relationship.last_attempt_amount

    if relationship.attempts_to_destination_24h >= 2 and last and abs(m.amount - last) <= 0.10 * last:
        return evidence("split_payments", VELOCITY, 10)

    return None


SIGNALS = (velocity_spike, new_payee_burst, high_outflow_ratio, retry_after_block, split_payments)
