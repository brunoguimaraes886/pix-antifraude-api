"""Política (4.2, seção 8): de P e ρ para a decisão.

| P                 | ρ       | decisão              | rule              |
|-------------------|---------|----------------------|-------------------|
| ≥ 50%             | —       | rejected             | risco_claro       |
| 10% ≤ P < 50%     | < 0,5   | rejected             | fundada_suspeita  |
| 10% ≤ P < 50%     | ≥ 0,5   | two_factor_required  | identidade        |
| < 10%, P·V·ρ > c₂ | —       | two_factor_required  | suspeita          |
| senão             | —       | approved             | risco_baixo       |

É a política de custo reescrita como regras: abaixo de 10% a comparação é
aprovar × 2FA, e o 2FA ganha quando a fraude que ele evita (P × V × ρ) vale
mais que o atrito de pedir a um cliente bom (c₂ = R$ 3).

O piso das regras duras vem por cima: uma camada só pode SUBIR a
severidade, nunca descer.
"""

from typing import Tuple

from engine import params
from engine.result import APPROVED, REJECTED, SEVERITY, TWO_FACTOR_REQUIRED

RISCO_CLARO = "risco_claro"
FUNDADA_SUSPEITA = "fundada_suspeita"
IDENTIDADE = "identidade"
SUSPEITA = "suspeita"
RISCO_BAIXO = "risco_baixo"
REGRA_DURA = "regra_dura"


def by_score(amount_reais: float, p: float, rho: float) -> Tuple[str, str]:
    if p >= params.P_RISCO_CLARO:
        return REJECTED, RISCO_CLARO

    if p >= params.P_FUNDADA_SUSPEITA:
        if rho >= params.RHO_IDENTITY:
            return TWO_FACTOR_REQUIRED, IDENTIDADE
        return REJECTED, FUNDADA_SUSPEITA

    if p * amount_reais * rho > params.C_2FA:
        return TWO_FACTOR_REQUIRED, SUSPEITA

    return APPROVED, RISCO_BAIXO


def decide(amount_reais: float, p: float, rho: float, floor: str = APPROVED) -> Tuple[str, str]:
    """A decisão do score, respeitando o piso das regras duras (empate fica com a regra dura)."""
    status, rule = by_score(amount_reais, p, rho)

    if floor != APPROVED and SEVERITY[floor] >= SEVERITY[status]:
        return floor, REGRA_DURA

    return status, rule
