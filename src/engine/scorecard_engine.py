"""O motor de decisão (4.2): regras duras → medidas → sinais → pontos → P e ρ → decisão.

    1. medidas e regras duras que não dependem do DICT (limite, sanções,
       apostas, insistência, destino bloqueado, aparelho não cadastrado).
       Rejeitou → para aqui: o DICT nem é consultado;
    2. consulta o DICT (`consult_dict()`) e roda as regras dele;
    3. sinais por família, com teto, mitigantes e assinaturas → pontos;
    4. pontos → probabilidade P e eficácia do 2FA ρ;
    5. política: P e ρ viram a decisão, respeitando o piso das regras duras;
    6. resposta: motivos, alerta, retenção recomendada e a camada interna.

Tudo puro sobre o `Features`: sem banco, rede nem relógio. O mesmo
`Features` gravado sempre dá a mesma decisão.
"""

from typing import List, Optional, Tuple

from engine import hard_rules, policy, response, signals
from engine.base import DictConsult, FraudEngine
from engine.evidence import Evidence
from engine.features import Features
from engine.measures import Measures, measure
from engine.reasons import Reason
from engine.result import REJECTED, EngineResult, most_severe
from engine.scoring import Score, score


class ScorecardEngine(FraudEngine):
    def evaluate(self, features: Features, consult_dict: DictConsult) -> EngineResult:
        measures = measure(features)
        outcomes = hard_rules.run(hard_rules.PRE_DICT_RULES, features, measures)

        if any(status == REJECTED for status, _ in outcomes):
            return self._stopped_before_dict(features, measures, outcomes)

        features.destination.dict = consult_dict()
        measures = measure(features)
        outcomes = outcomes + hard_rules.run(hard_rules.DICT_RULES, features, measures)

        evidences = signals.collect(features, measures)
        points = score(evidences)

        floor = most_severe([status for status, _ in outcomes])
        status, rule = policy.decide(measures.amount_reais, points.probability, points.rho, floor)

        return EngineResult(
            status=status,
            reasons=_reasons(outcomes, evidences),
            score=float(points.points),
            alert=response.alert_for(status, evidences, [reason.code for _, reason in outcomes]),
            hold_recommended=response.hold_recommended(status, points),
            decision=_decision(features, measures, outcomes, evidences, points, status, rule),
        )

    def _stopped_before_dict(
        self, features: Features, measures: Measures, outcomes: List[Tuple[str, Reason]]
    ) -> EngineResult:
        status = most_severe([status for status, _ in outcomes])

        return EngineResult(
            status=status,
            reasons=_reasons(outcomes, []),
            decision=_decision(features, measures, outcomes, [], None, status, policy.REGRA_DURA),
        )


def _reasons(outcomes: List[Tuple[str, Reason]], evidences: List[Evidence]) -> List[Reason]:
    """Regras duras na ordem em que dispararam (sem pontos); depois os sinais, do maior para o menor.

    Um sinal com o mesmo código de uma regra dura (`dict_unavailable`) não
    se repete: fica a linha da regra; os pontos do sinal ficam na camada
    interna.
    """
    reasons = []
    seen = set()

    for _, reason in outcomes:
        if reason.code not in seen:
            seen.add(reason.code)
            reasons.append(reason)

    for ev in sorted(evidences, key=lambda ev: -ev.points):
        if ev.code not in seen:
            seen.add(ev.code)
            reasons.append(ev.reason)

    return reasons


def _decision(
    features: Features,
    measures: Measures,
    outcomes: List[Tuple[str, Reason]],
    evidences: List[Evidence],
    points: Optional[Score],
    status: str,
    rule: str,
) -> dict:
    """A camada interna: tudo o que explica a decisão, para risco, PLD e calibração."""
    hard_codes = {reason.code for _, reason in outcomes}
    codes = hard_codes | {ev.code for ev in evidences}

    threat = response.threat(points, evidences) if points is not None else None

    basis = None
    if status == REJECTED:
        basis = "own_evidence"
        score_alone = policy.by_score(measures.amount_reais, points.probability, points.rho)[0] if points else None
        rejected_by = {reason.code for outcome_status, reason in outcomes if outcome_status == REJECTED}
        if rejected_by == {"dict_fraud_marker"} and score_alone != REJECTED:
            basis = "third_party_mark"

    decision = {
        "status": status,
        "rule": rule,
        "hard_rules": [{"code": reason.code, "status": outcome_status} for outcome_status, reason in outcomes],
        "stopped_before_dict": features.destination.dict is None,
        "threat": threat,
        "situation_type": response.situation_type(threat, evidences) if status == REJECTED else None,
        "basis": basis,
        "pld_alert": response.pld_alert(points, codes) or measures.payer_dict_marked,
        "sanctions_freeze": "sanctioned_party" in hard_codes,
        "destination_evidence": response.destination_evidence(points, hard_codes),
        "effective_limit": hard_rules.effective_limit(features, measures),
        "measures": {
            "p90_blend": round(measures.p90_blend),
            "amount_ratio": round(measures.amount_ratio, 4),
            "balance_share": _round(measures.balance_share),
            "exit_ratio_with_pix": _round(measures.exit_ratio_with_pix),
            "pass_through_with_pix": _round(measures.pass_through_with_pix),
            "payer_inflow_jump": _round(measures.payer_inflow_jump),
            "destination_inflow_jump": _round(measures.destination_inflow_jump),
            "first_payment": measures.first_payment,
            "escalating": measures.escalating,
            "recurring": measures.recurring,
            "device_registered": measures.device_registered,
            "cold_start": measures.cold_start,
            "dict_recent": measures.dict_recent,
            "fan_in": measures.fan_in,
            "new_payees_period": measures.new_payees_period,
            "payer_dict_marked": measures.payer_dict_marked,
        },
    }

    if points is not None:
        decision.update(
            {
                "points": points.points,
                "probability": round(points.probability, 6),
                "rho": round(points.rho, 4),
                "positive_points": points.positive_points,
                "mitigation_points": points.mitigation_points,
                "family_points": points.family_points,
                "signals": [
                    {"code": ev.code, "family": ev.family, "points": ev.points, "rho": ev.rho} for ev in evidences
                ],
            }
        )

    return decision


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 4)
