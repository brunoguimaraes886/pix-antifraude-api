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
    """O que o motor devolve.

    - `status` e `reasons`: a decisão e por quê. No `approved` a lista de
      motivos vem vazia (é o contrato da resposta). Os motivos são os
      internos, com pontos; a resposta pública é montada a partir deles
      (src/engine/response.py), escondendo o que é sensível a PLD.
    - `score`: os pontos do Pix (escala de log-odds), quando o motor chegou
      a calcular.
    - `alert` e `hold_recommended`: a parte pública da camada de alerta.
    - `decision`: a camada interna (sinais, P, ρ, ameaça, PLD). Nunca sai
      na resposta da API.
    """

    status: str
    reasons: List[Reason] = field(default_factory=list)
    score: Optional[float] = None
    alert: Optional[str] = None
    hold_recommended: bool = False
    decision: Optional[dict] = None


def most_severe(statuses: List[str]) -> str:
    if not statuses:
        return APPROVED

    return max(statuses, key=lambda status: SEVERITY[status])
