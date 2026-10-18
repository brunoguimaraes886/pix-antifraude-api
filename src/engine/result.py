from dataclasses import dataclass, field
from typing import List, Optional

from engine.reasons import Reason

APPROVED = "approved"
TWO_FACTOR_REQUIRED = "two_factor_required"
REJECTED = "rejected"

STATUSES = (APPROVED, TWO_FACTOR_REQUIRED, REJECTED)

# Quando várias regras disparam, vale a decisão mais severa.
SEVERITY = {APPROVED: 0, TWO_FACTOR_REQUIRED: 1, REJECTED: 2}


@dataclass
class EngineResult:
    """O que o motor devolve: a decisão, os motivos e, se houver, um score.

    No `approved` a lista de motivos vem vazia (é o contrato da resposta).
    O score é opcional: o motor não precisa calcular um número.
    """

    status: str
    reasons: List[Reason] = field(default_factory=list)
    score: Optional[float] = None


def most_severe(statuses: List[str]) -> str:
    if not statuses:
        return APPROVED

    return max(statuses, key=lambda status: SEVERITY[status])
