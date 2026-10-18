"""Relação: o pagador conhece este destino? (4.2, seção 5.4 — teto 30, ρ = 0,3)

Os mitigantes (pontos negativos) só aliviam o score, nunca uma regra dura.
"""

from typing import Optional

from engine.evidence import Evidence, evidence
from engine.features import Features
from engine.measures import Measures
from engine.params import RELATIONSHIP


def first_payment_to_destination(f: Features, m: Measures) -> Optional[Evidence]:
    if m.first_payment and not m.same_owner:
        return evidence("first_payment_to_destination", RELATIONSHIP, 15)
    return None


def own_account_new(f: Features, m: Measures) -> Optional[Evidence]:
    """"Conta segura" em nome da vítima — ou portabilidade legítima: nunca rejeita sozinho."""
    if m.same_owner and m.destination_age_days < 30:
        return evidence("own_account_new", RELATIONSHIP, 15)
    return None


def escalating_payments(f: Features, m: Measures) -> Optional[Evidence]:
    """Investimento, amor, tarefas: começa pequeno e cresce."""
    if m.escalating:
        return evidence("escalating_payments", RELATIONSHIP, 15)
    return None


def test_then_large(f: Features, m: Measures) -> Optional[Evidence]:
    """Pix-teste de até R$ 20 e, em menos de 24h, um valor 10× maior (GAFI)."""
    largest = f.relationship.max_previous_out_amount

    if (
        not m.escalating
        and m.relationship_age_days is not None
        and m.relationship_age_days < 1
        and largest is not None
        and largest <= 2_000
        and m.amount >= 10 * largest
    ):
        return evidence("test_then_large", RELATIONSHIP, 10)

    return None


def recurring_destination(f: Features, m: Measures) -> Optional[Evidence]:
    """Aluguel, família, contas: lista de confiança automática."""
    if m.recurring:
        return evidence("recurring_destination", RELATIONSHIP, -20)
    return None


def received_from_destination(f: Features, m: Measures) -> Optional[Evidence]:
    """Mão dupla: o destino já pagou ≥ R$ 50 a esta conta, há ≥ 30 dias."""
    if m.two_way and not m.escalating:
        return evidence("received_from_destination", RELATIONSHIP, -10)
    return None


def own_account_established(f: Features, m: Measures) -> Optional[Evidence]:
    if m.same_owner and m.destination_age_days >= 180:
        return evidence("own_account_established", RELATIONSHIP, -20)
    return None


SIGNALS = (
    first_payment_to_destination,
    own_account_new,
    escalating_payments,
    test_then_large,
    recurring_destination,
    received_from_destination,
    own_account_established,
)
