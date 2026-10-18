from typing import Callable, List, Optional, Tuple

from engine.base import FraudEngine
from engine.features import DICT_UNAVAILABLE, Features
from engine.reasons import DICT_FRAUD_MARKER, DICT_UNAVAILABLE as DICT_UNAVAILABLE_REASON, LIMIT_EXCEEDED, Reason
from engine.result import APPROVED, REJECTED, TWO_FACTOR_REQUIRED, EngineResult, most_severe

Outcome = Optional[Tuple[str, Reason]]


class RulesEngine(FraudEngine):
    """Motor PROVISÓRIO: só os vetos, para a API rodar de ponta a ponta.

    O motor de verdade (pesos, tipping points, golpes) entra no lugar deste
    — ou dentro dele, como mais regras na lista. Até lá, ficam só as regras
    que não dependem de calibração:

      1. limit_exceeded   → rejected   o Pix passa do limite do período
                                        (decidido: "passou do limite →
                                        bloqueia na hora");
      2. dict_fraud_marker → rejected  o destino tem marcação de fraude
                                        no DICT (veto);
      3. dict_unavailable → 2FA        destino de outro banco sem DICT
                                        nenhum: na dúvida, o cliente confirma.

    Cada regra devolve (status, motivo) ou None. Todas rodam; a decisão é a
    mais severa e os motivos são todos os que dispararam.
    """

    def __init__(self) -> None:
        self.rules: List[Callable[[Features], Outcome]] = [
            self.limit_exceeded,
            self.dict_fraud_marker,
            self.dict_unavailable,
        ]

    def evaluate(self, features: Features) -> EngineResult:
        outcomes = []
        for rule in self.rules:
            outcome = rule(features)
            if outcome is not None:
                outcomes.append(outcome)

        if not outcomes:
            return EngineResult(status=APPROVED)

        status = most_severe([outcome_status for outcome_status, _ in outcomes])
        reasons = [reason for _, reason in outcomes]

        return EngineResult(status=status, reasons=reasons)

    @staticmethod
    def limit_exceeded(features: Features) -> Outcome:
        period = features.payer.current_period
        spent_with_this_pix = period.outflow.amount + features.transaction.amount

        if spent_with_this_pix > period.limit:
            return REJECTED, LIMIT_EXCEEDED

        return None

    @staticmethod
    def dict_fraud_marker(features: Features) -> Outcome:
        if count_fraud_markers(features.destination.dict.response) > 0:
            return REJECTED, DICT_FRAUD_MARKER

        return None

    @staticmethod
    def dict_unavailable(features: Features) -> Outcome:
        destination = features.destination

        if not destination.is_internal and destination.dict.status == DICT_UNAVAILABLE:
            return TWO_FACTOR_REQUIRED, DICT_UNAVAILABLE_REASON

        return None


def count_fraud_markers(dict_response: Optional[dict]) -> int:
    """Quantas marcações de fraude o DICT devolveu, somando conta e dono.

    Lê com cuidado: o formato vem de fora, e um campo faltando não pode
    derrubar a decisão.
    """
    if not isinstance(dict_response, dict):
        return 0

    total = 0
    for subject in ("account", "owner"):
        markers = (dict_response.get(subject) or {}).get("fraud_markers") or []
        if isinstance(markers, list):
            total = total + len(markers)

    return total
