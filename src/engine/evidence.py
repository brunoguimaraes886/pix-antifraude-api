from dataclasses import dataclass
from typing import Optional

from engine.reasons import Reason, signal


@dataclass(frozen=True)
class Evidence:
    """Um sinal que disparou: quantos pontos soma e em que família.

    `rho` só nas assinaturas (família `pattern`): cada uma carrega a eficácia
    do 2FA da ameaça que representa. Nos outros sinais vale o ρ da família.
    """

    code: str
    family: str
    points: int
    rho: Optional[float] = None

    @property
    def reason(self) -> Reason:
        return signal(self.code, self.points)


def evidence(code: str, family: str, points: float, rho: Optional[float] = None) -> Evidence:
    return Evidence(code, family, int(round(points)), rho)
