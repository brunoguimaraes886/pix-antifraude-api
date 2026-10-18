"""A resposta em duas camadas (4.2, seção 9).

Pública (o que o cliente e o canal veem): status, motivos legíveis, alerta
e retenção recomendada. Motivos sensíveis a PLD viram um único
`risk_policy`: avisar o cliente de suspeita de lavagem é proibido (Lei
9.613, art. 11, II; Circular 3.978, art. 50).

Interna (só a equipe de risco e PLD, em `transaction_analysis.decision`):
todos os sinais com pontos, P, ρ, ameaça, causa no vocabulário do DICT,
base da rejeição e alertas de PLD e de sanções.
"""

from typing import Iterable, List, Optional, Set

from engine import params
from engine.evidence import Evidence
from engine.reasons import PLD_SENSITIVE, RISK_POLICY, Reason
from engine.result import REJECTED, TWO_FACTOR_REQUIRED
from engine.scoring import Score

PUBLIC_SIGNALS = 3          # sinais de maior peso na resposta pública (além das regras duras)

IDENTIDADE = "identidade"
LARANJA = "laranja"
GOLPE = "golpe"

MULE_PATTERNS = ("fresh_mule", "mule_cashout")
DESTINATION_HARD_RULES = ("dict_fraud_marker", "dict_marker", "destination_account_blocked")


# ── Pública ──────────────────────────────────────────────────────


def public_reasons(reasons: Iterable[Reason]) -> List[Reason]:
    """Regras duras primeiro (na ordem em que dispararam), depois os sinais de maior peso.

    Sem pontos = regra dura ou recusa operacional. Mitigantes (pontos
    negativos) nunca aparecem. Sensível a PLD vira `risk_policy`.
    """
    reasons = list(reasons)
    hard = [reason for reason in reasons if reason.points is None]
    signals = sorted((reason for reason in reasons if reason.points is not None and reason.points > 0),
                     key=lambda reason: -reason.points)

    public = []
    seen = set()
    for reason in hard + signals[:PUBLIC_SIGNALS]:
        shown = RISK_POLICY if reason.code in PLD_SENSITIVE else Reason(reason.code, reason.message)
        if shown.code not in seen:
            seen.add(shown.code)
            public.append(shown)

    return public


ALERTS = (
    (("safe_account_pattern", "own_account_new"),
     "O banco nunca pede para transferir seu dinheiro para uma \"conta segura\". Se alguém pediu, é golpe."),
    (("refund_to_third_party",),
     "Este valor é igual a um Pix que você recebeu. Devolução se faz pela função de devolução, "
     "que volta para quem pagou."),
    (("scam_ladder", "escalating_payments"),
     "Os valores para esta conta estão crescendo rápido. Investimento com retorno garantido é golpe."),
    (("dict_marker", "dict_history"),
     "Este destino tem registro de suspeita de fraude. Confira quem vai receber antes de seguir."),
    (("scam_drain_pattern", "balance_drain", "high_outflow_ratio"),
     "Este Pix leva quase todo o seu saldo. Se alguém pediu urgência por telefone ou mensagem, é golpe."),
    (("night_coercion", "unusual_night"),
     "Pix noturno fora do seu hábito. Confirme que está tudo bem antes de seguir."),
    (("new_device", "new_device_limit", "takeover_cashout", "impossible_travel", "far_from_last_location",
      "shared_device"),
     "Confirme que é você: este Pix saiu de um aparelho ou de um local diferente do habitual."),
    (("new_destination_account", "destination_fan_in", "fresh_mule", "destination_rejected_before"),
     "Você nunca pagou esta conta e ela tem sinais de risco. Se alguém pediu este Pix por telefone ou "
     "mensagem, desligue e fale com o banco."),
    (("first_payment_to_destination",),
     "Primeiro Pix para este destino. Se alguém pediu este Pix por telefone ou mensagem, desligue e fale "
     "com o banco."),
)
DEFAULT_ALERT = "Confirme este Pix. Se alguém pediu por telefone ou mensagem, desligue e fale com o banco."


def alert_for(status: str, evidences: List[Evidence], hard_codes: List[str]) -> Optional[str]:
    """Só no 2FA: uma frase a partir do sinal mais forte. Nunca fala de PLD."""
    if status != TWO_FACTOR_REQUIRED:
        return None

    ranked = [ev.code for ev in sorted(evidences, key=lambda ev: -ev.points) if ev.points > 0]
    message_by_code = {code: message for codes, message in ALERTS for code in codes}

    # Regras duras primeiro; depois o sinal de maior peso que tem frase própria.
    for code in list(hard_codes) + ranked:
        if code in message_by_code:
            return message_by_code[code]

    return DEFAULT_ALERT


def hold_recommended(status: str, score: Optional[Score]) -> bool:
    """2FA de golpe ou laranja (ρ < 0,5): em produção vira retenção pelo temporizador (30/60 min)."""
    return (
        status == TWO_FACTOR_REQUIRED
        and score is not None
        and score.positive_points > 0
        and score.rho < params.RHO_IDENTITY
    )


# ── Interna ──────────────────────────────────────────────────────


def threat(score: Score, evidences: List[Evidence]) -> Optional[str]:
    if score.positive_points <= 0:
        return None

    if score.rho >= params.RHO_IDENTITY:
        return IDENTIDADE

    mule_points = score.family_points.get(params.DESTINATION, 0) + score.family_points.get(params.PAYER_MULE, 0)
    mule_points += min(
        params.FAMILIES[params.PATTERN][0], sum(ev.points for ev in evidences if ev.code in MULE_PATTERNS)
    )

    return LARANJA if mule_points * 2 >= score.positive_points else GOLPE


def situation_type(threat_name: Optional[str], evidences: List[Evidence]) -> Optional[str]:
    """A causa no vocabulário do DICT, para a notificação de infração."""
    if threat_name is None:
        return None

    if threat_name == IDENTIDADE:
        return "ACCOUNT_TAKEOVER"

    positive = [ev for ev in evidences if ev.points > 0]
    if positive and max(positive, key=lambda ev: ev.points).code == "night_coercion":
        return "COERCION"

    return "SCAM"


def destination_evidence(score: Optional[Score], hard_codes: Set[str]) -> bool:
    """A suspeita é sobre o destino? (alimenta `fraud_rejected_payers_90d` de outros clientes)"""
    if hard_codes & set(DESTINATION_HARD_RULES):
        return True

    if score is None or not score.family_points:
        return False

    destination_points = score.family_points.get(params.DESTINATION, 0)
    return destination_points > 0 and destination_points >= max(score.family_points.values())


def pld_alert(score: Optional[Score], codes: Set[str]) -> bool:
    """Marca o Pix para a equipe de PLD. Não muda a decisão."""
    if codes & {"mule_cashout", "split_payments", "new_device_structuring"}:
        return True

    return score is not None and score.family_points.get(params.PAYER_MULE, 0) >= 20
