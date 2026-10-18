"""Os sinais do score, por família. Cada sinal é uma função pura (features, medidas) → Evidence | None."""

from typing import List

from engine.evidence import Evidence
from engine.features import Features
from engine.measures import Measures
from engine.signals import context, destination, identity, magnitude, patterns, payer_mule, relationship, velocity

FAMILY_SIGNALS = (
    identity.SIGNALS
    + magnitude.SIGNALS
    + velocity.SIGNALS
    + relationship.SIGNALS
    + destination.SIGNALS
    + payer_mule.SIGNALS
    + context.SIGNALS
)


def collect(f: Features, m: Measures) -> List[Evidence]:
    """Todos os sinais que dispararam, assinaturas por último (elas olham os anteriores)."""
    evidences = [ev for ev in (signal(f, m) for signal in FAMILY_SIGNALS) if ev is not None]
    fired = {ev.code for ev in evidences}

    for pattern in patterns.SIGNALS:
        ev = pattern(f, m, fired)
        if ev is not None:
            evidences.append(ev)

    return evidences
