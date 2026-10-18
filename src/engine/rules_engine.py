from typing import Callable, List, Optional, Tuple

from engine.base import DictConsult, FraudEngine
from engine.features import DICT_UNAVAILABLE, Features
from engine.reasons import DICT_FRAUD_MARKER, DICT_UNAVAILABLE as DICT_UNAVAILABLE_REASON, LIMIT_EXCEEDED, Reason
from engine.result import APPROVED, REJECTED, TWO_FACTOR_REQUIRED, EngineResult, most_severe

Outcome = Optional[Tuple[str, Reason]]
Rule = Callable[[Features], Outcome]


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

    A regra 1 roda antes do DICT: se ela rejeita, o DICT nem é consultado.
    As regras 2 e 3 rodam depois da consulta.

    Cada regra devolve (status, motivo) ou None. Todas as da fase rodam; a
    decisão é a mais severa e os motivos são todos os que dispararam.
    """

    def __init__(self) -> None:
        self.pre_dict_rules: List[Rule] = [
            self.limit_exceeded,
        ]
        self.dict_rules: List[Rule] = [
            self.dict_fraud_marker,
            self.dict_unavailable,
        ]

    def evaluate(self, features: Features, consult_dict: DictConsult) -> EngineResult:
        outcomes = run_rules(self.pre_dict_rules, features)

        if any(status == REJECTED for status, _ in outcomes):
            return to_result(outcomes)

        features.destination.dict = consult_dict()
        outcomes = outcomes + run_rules(self.dict_rules, features)

        return to_result(outcomes)

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


def run_rules(rules: List[Rule], features: Features) -> List[Tuple[str, Reason]]:
    outcomes = []
    for rule in rules:
        outcome = rule(features)
        if outcome is not None:
            outcomes.append(outcome)

    return outcomes


def to_result(outcomes: List[Tuple[str, Reason]]) -> EngineResult:
    if not outcomes:
        return EngineResult(status=APPROVED)

    status = most_severe([outcome_status for outcome_status, _ in outcomes])
    reasons = [reason for _, reason in outcomes]

    return EngineResult(status=status, reasons=reasons)


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
