"""De sinais para pontos, P e ρ (4.2, seções 5 e 7).

    logit(P) = ln(PRIOR_ODDS) + (pontos / PDO) · ln 2
    ρ        = Σ(pontos da família × ρ da família) / Σ pontos positivos

Dentro de cada família os pontos positivos se somam até o teto. Os
mitigantes (negativos) entram depois, com piso total de −40.
"""

from dataclasses import dataclass, field
from typing import Dict, List

from engine import params
from engine.evidence import Evidence


@dataclass
class Score:
    points: int
    probability: float
    rho: float
    positive_points: int
    mitigation_points: int
    family_points: Dict[str, int] = field(default_factory=dict)   # já com o teto


def probability(points: float) -> float:
    odds = params.PRIOR_ODDS * 2 ** (points / params.PDO)
    return odds / (1 + odds)


def score(evidences: List[Evidence]) -> Score:
    by_family: Dict[str, List[Evidence]] = {}
    mitigation = 0

    for ev in evidences:
        if ev.points < 0:
            mitigation += ev.points
        elif ev.points > 0:
            by_family.setdefault(ev.family, []).append(ev)

    positive = 0
    weighted_rho = 0.0
    family_points = {}

    for family, family_evidences in by_family.items():
        cap, family_rho = params.FAMILIES[family]
        raw = sum(ev.points for ev in family_evidences)
        rho = sum(ev.points * (ev.rho if ev.rho is not None else family_rho) for ev in family_evidences) / raw
        capped = min(raw, cap)

        family_points[family] = capped
        positive += capped
        weighted_rho += capped * rho

    mitigation = max(mitigation, params.MITIGATION_FLOOR)
    points = positive + mitigation

    return Score(
        points=points,
        probability=probability(points),
        rho=weighted_rho / positive if positive else 0.0,
        positive_points=positive,
        mitigation_points=mitigation,
        family_points=family_points,
    )
