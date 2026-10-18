"""Magnitude: o valor foge do habitual? (4.2, seção 5.2 — teto 40, ρ = 0,4)"""

import math
from typing import Optional

from engine.evidence import Evidence, evidence
from engine.features import Features
from engine.measures import Measures
from engine.params import MAGNITUDE


def amount_above_profile(f: Features, m: Measures) -> Optional[Evidence]:
    """8 · log2(valor / p90 combinado), entre 0 e 30: contínuo, sem degrau para o golpista explorar."""
    if m.amount_ratio <= 1:
        return None

    points = min(30.0, 8 * math.log2(m.amount_ratio))
    if round(points) <= 0:
        return None

    return evidence("amount_above_profile", MAGNITUDE, points)


def balance_drain(f: Features, m: Measures) -> Optional[Evidence]:
    """"Zera a conta": assinatura da falsa central e do sequestro."""
    share = m.balance_share
    if share is None:
        return None

    for minimum, points in ((0.95, 24), (0.80, 16), (0.50, 8)):
        if share >= minimum:
            return evidence("balance_drain", MAGNITUDE, points)

    return None


SIGNALS = (amount_above_profile, balance_drain)
