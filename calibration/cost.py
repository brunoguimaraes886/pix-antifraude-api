"""Quanto custa cada decisão, dado o que o cenário realmente era (o "juiz").

Este é o custo REAL usado para avaliar o motor, separado dos custos que o
motor usa por dentro (params.C_2FA etc.), que são os que a busca ajusta. Se
fossem o mesmo número, a busca poderia "ganhar" mexendo no juiz.

    golpe aprovado      → perde o valor do Pix (V)
    golpe com 2FA       → perde V × (1 − chance de o 2FA parar esse golpe)
    golpe rejeitado     → 0
    legítimo aprovado   → 0
    legítimo com 2FA    → atrito (R$ 3)
    legítimo rejeitado  → R$ 20 + 10% de V, a parte proporcional até R$ 300
                          (cliente sem o Pix, SAC, risco de churn; ele ainda pode
                          pagar de outro jeito, então não cresce sem fim)

A base de cenários tem muito mais golpe do que a vida real (1 em 10.000).
Por isso cada legítimo vale LEGIT_WEIGHT vezes: quantos clientes bons
parecidos existem para cada golpe parecido. Esse número não se sabe ao
certo, então a busca otimiza a média relativa em LEGIT_WEIGHTS.
"""

from engine.result import APPROVED, REJECTED, TWO_FACTOR_REQUIRED

FRICTION_2FA = 3.0
REJECT_FIXED = 20.0
REJECT_SHARE = 0.10
REJECT_SHARE_CAP = 300.0

# Chance de o 2FA parar o golpe, por quem apertou o botão.
STOP_INTRUDER = 0.9     # outra pessoa: não tem a biometria/senha do dono
STOP_DECEIVED = 0.2     # o dono enganado: confirma o que o golpista mandou
STOP_MULE = 0.05        # o dono é o laranja/cúmplice: confirma sem pensar

LEGIT_WEIGHTS = (10, 50, 200)
LEGIT_WEIGHT = 50       # o do relatório principal

MULE_WORDS = ("laranja", "mule", "cumplic", "cúmplic", "alugada", "aluguel_de_conta")


def stop_chance(scenario: dict) -> float:
    if scenario.get("operator") == "intruder":
        return STOP_INTRUDER
    fraud_type = (scenario.get("fraud_type") or "").lower()
    if any(word in fraud_type for word in MULE_WORDS):
        return STOP_MULE
    return STOP_DECEIVED


def amount(scenario: dict) -> float:
    return float((scenario.get("pix") or {}).get("amount", 150.0))


def fraud_cost(scenario: dict, status: str) -> float:
    if status == APPROVED:
        return amount(scenario)
    if status == TWO_FACTOR_REQUIRED:
        return amount(scenario) * (1 - stop_chance(scenario))
    return 0.0


def legit_cost(scenario: dict, status: str) -> float:
    if status == TWO_FACTOR_REQUIRED:
        return FRICTION_2FA
    if status == REJECTED:
        return REJECT_FIXED + min(REJECT_SHARE * amount(scenario), REJECT_SHARE_CAP)
    return 0.0


def cost(scenario: dict, status: str, legit_weight: float = LEGIT_WEIGHT) -> float:
    if scenario["label"] == "fraud":
        return fraud_cost(scenario, status)
    return legit_weight * legit_cost(scenario, status)
