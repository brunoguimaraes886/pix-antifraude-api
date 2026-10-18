"""O catálogo de motivos. Todo motivo que sai na resposta nasce aqui.

O `code` é o contrato (quem integra programa em cima dele); a `message` é
para gente ler. As mensagens são qualitativas ("aberta recentemente", não
"há 3 dias") e não dizem nada sobre outros clientes (sigilo bancário).

`points` só existe nos sinais do score: é quanto o sinal somou naquele Pix
(vai para `analysis_reason.points`). Regras duras e recusas operacionais
ficam sem pontos.
"""

from dataclasses import dataclass, replace
from typing import Optional


@dataclass(frozen=True)
class Reason:
    code: str
    message: str
    points: Optional[int] = None

    def with_points(self, points: Optional[int]) -> "Reason":
        return replace(self, points=points)


# ────────────────────────────────────────────────────────────────
# Operacionais: a API recusa antes do motor, porque o Pix não tem como
# sair do jeito que veio. Não são sinal de fraude e por isso NÃO contam
# como "Pix bloqueado" no resumo diário (account_baseline).
# ────────────────────────────────────────────────────────────────

UNKNOWN_ACCOUNT = Reason("unknown_account", "A conta pagadora não existe no nosso banco.")
ACCOUNT_OWNER_MISMATCH = Reason("account_owner_mismatch", "O CPF/CNPJ informado não é o titular da conta pagadora.")
UNKNOWN_DESTINATION_ACCOUNT = Reason("unknown_destination_account", "A conta de destino é do nosso banco, mas não existe.")
DESTINATION_OWNER_MISMATCH = Reason(
    "destination_owner_mismatch", "O CPF/CNPJ informado não é o titular da conta de destino."
)
ACCOUNT_BLOCKED = Reason("account_blocked", "A conta pagadora está bloqueada.")
INSUFFICIENT_BALANCE = Reason("insufficient_balance", "A conta pagadora não tem saldo para este Pix.")

OPERATIONAL_REASONS = (
    UNKNOWN_ACCOUNT,
    ACCOUNT_OWNER_MISMATCH,
    UNKNOWN_DESTINATION_ACCOUNT,
    DESTINATION_OWNER_MISMATCH,
    ACCOUNT_BLOCKED,
    INSUFFICIENT_BALANCE,
)
OPERATIONAL_CODES = tuple(reason.code for reason in OPERATIONAL_REASONS)

# O motor quebrou: o Pix não sai sem confirmação (fail-safe).
ENGINE_ERROR = Reason("engine_error", "O motor antifraude falhou; o Pix precisa de confirmação.")


# ────────────────────────────────────────────────────────────────
# Regras duras do motor (4.2, seção 3)
# ────────────────────────────────────────────────────────────────

SANCTIONED_PARTY = Reason("sanctioned_party", "Uma das partes está em lista de sanções; o Pix não pode ser feito.")
BETTING_DESTINATION = Reason("betting_destination", "Pix para operadora de apostas não é permitido.")
LIMIT_EXCEEDED = Reason("limit_exceeded", "O Pix passa do limite do período (diurno ou noturno).")
REPEAT_AFTER_FRAUD_REJECTION = Reason(
    "repeat_after_fraud_rejection", "Um Pix para este destino foi recusado por segurança nas últimas 24 horas."
)
DESTINATION_ACCOUNT_BLOCKED = Reason("destination_account_blocked", "A conta de destino está bloqueada.")
DICT_FRAUD_MARKER = Reason("dict_fraud_marker", "A conta ou o CPF/CNPJ de destino tem marcação de fraude no DICT.")
PAYER_DICT_FRAUD_MARKER = Reason(
    "payer_dict_fraud_marker", "A conta pagadora ou o CPF/CNPJ dela tem marcação de fraude no DICT."
)
DICT_MARKER = Reason("dict_marker", "O destino tem registro de suspeita de fraude no Banco Central.")
NEW_DEVICE_LIMIT = Reason(
    "new_device_limit", "Aparelho não cadastrado: acima de R$ 200 por Pix ou R$ 1.000 no dia, é preciso confirmar."
)
NEW_DEVICE_STRUCTURING = Reason(
    "new_device_structuring", "Vários Pix logo abaixo do limite do aparelho não cadastrado."
)
DICT_UNAVAILABLE = Reason("dict_unavailable", "O DICT não respondeu e não há consulta recente deste destino.")


# ────────────────────────────────────────────────────────────────
# Sinais do score (4.2, seções 5 e 6)
# ────────────────────────────────────────────────────────────────

DESTINATION_RISK_MESSAGE = "A conta de destino tem sinais de risco."

SIGNALS = {
    reason.code: reason
    for reason in (
        # Identidade
        Reason("new_device", "Pix feito de um aparelho não cadastrado."),
        Reason("new_ip", "Endereço de rede nunca usado nesta conta."),
        Reason("shared_device", "O aparelho foi usado por outras contas."),
        Reason("new_channel", "Canal nunca usado nesta conta."),
        Reason("far_from_last_location", "Pix feito longe do local do último Pix."),
        Reason("impossible_travel", "Localização incompatível com a do último Pix."),
        # Magnitude
        Reason("amount_above_profile", "Valor acima do habitual da conta."),
        Reason("balance_drain", "O Pix leva a maior parte do saldo."),
        # Ritmo e acumulado
        Reason("velocity_spike", "Muitos Pix em pouco tempo."),
        Reason("new_payee_burst", "Vários destinos novos no mesmo período."),
        Reason("high_outflow_ratio", "A conta está sendo esvaziada em vários Pix."),
        Reason("retry_after_block", "Nova tentativa depois de um Pix barrado."),
        Reason("split_payments", "Pix repetidos de valor parecido para o mesmo destino."),
        # Relação
        Reason("first_payment_to_destination", "Primeiro Pix para este destino."),
        Reason("own_account_new", "A conta de destino é sua e foi aberta recentemente."),
        Reason("escalating_payments", "Os valores para este destino estão crescendo."),
        Reason("test_then_large", "Um Pix pequeno de teste seguido de um valor alto."),
        Reason("recurring_destination", "Destino recorrente."),
        Reason("received_from_destination", "O destino já pagou esta conta."),
        Reason("own_account_established", "Transferência entre contas próprias."),
        # Destino
        Reason("dict_history", "O destino tem registro de fraude no Banco Central."),
        Reason("new_destination_account", "A conta de destino foi aberta recentemente."),
        Reason("destination_fan_in", DESTINATION_RISK_MESSAGE),
        Reason("destination_rejected_before", DESTINATION_RISK_MESSAGE),
        Reason("destination_pass_through", DESTINATION_RISK_MESSAGE),
        Reason("destination_inflow_jump", DESTINATION_RISK_MESSAGE),
        Reason("destination_dormant_awakened", DESTINATION_RISK_MESSAGE),
        Reason("destination_block_history", DESTINATION_RISK_MESSAGE),
        # Pagador como laranja (todos sensíveis a PLD)
        Reason("payer_pass_through", "Entradas de vários pagadores novos repassadas em seguida."),
        Reason("new_source_account", "Conta pagadora nova repassando entradas."),
        Reason("payer_inflow_jump", "Entradas muito acima do habitual da conta."),
        Reason("payer_dormant_awakened", "Conta parada que voltou a movimentar."),
        # Contexto
        Reason("unusual_night", "Pix no período noturno, fora do hábito da conta."),
        Reason("source_risk_history", "A conta tem histórico de bloqueios ou Pix recusados."),
        Reason("dict_unavailable", DICT_UNAVAILABLE.message),
        Reason("missing_geolocation", "Pix sem a localização do aparelho."),
        # Assinaturas
        Reason("scam_drain_pattern", "Padrão de golpe: esvaziar a conta para um destino novo."),
        Reason("safe_account_pattern", "Padrão do golpe da \"conta segura\"."),
        Reason("refund_to_third_party", "Padrão do golpe do \"Pix errado\"."),
        Reason("scam_ladder", "Padrão de golpe com valores crescentes."),
        Reason("takeover_cashout", "Padrão de invasão de conta."),
        Reason("night_coercion", "Padrão de coação: vários Pix no período noturno."),
        Reason("fresh_mule", DESTINATION_RISK_MESSAGE),
        Reason("mule_cashout", "Repasse de entradas recentes para um destino novo."),
    )
}


def signal(code: str, points: int) -> Reason:
    return SIGNALS[code].with_points(points)


# ────────────────────────────────────────────────────────────────
# Sigilo (Lei 9.613, art. 11, II): o cliente nunca fica sabendo que há
# suspeita de lavagem. Na resposta pública, estes motivos viram um só,
# genérico.
# ────────────────────────────────────────────────────────────────

RISK_POLICY = Reason("risk_policy", "Transação não autorizada pela política de segurança.")

PLD_SENSITIVE = (
    "payer_pass_through",
    "payer_inflow_jump",
    "payer_dormant_awakened",
    "new_source_account",
    "payer_dict_fraud_marker",
    "mule_cashout",
    "split_payments",
    "new_device_structuring",
)


# ────────────────────────────────────────────────────────────────
# Rejeição que não é suspeita: só limite ou motivo operacional. Não conta
# como "Pix rejeitado" no resumo diário nem nas regras de insistência.
# ────────────────────────────────────────────────────────────────

NOT_SUSPICION_CODES = OPERATIONAL_CODES + (LIMIT_EXCEEDED.code,)


# ────────────────────────────────────────────────────────────────
# O que uma liberação manual NÃO desfaz: as obrigações (limite, marcação
# no DICT, sanções, apostas, destino bloqueado, regras do aparelho não
# cadastrado) e o motor quebrado (sem decisão, não há o que liberar).
# ────────────────────────────────────────────────────────────────

NOT_RELEASABLE = (
    LIMIT_EXCEEDED,
    DICT_FRAUD_MARKER,
    PAYER_DICT_FRAUD_MARKER,
    ENGINE_ERROR,
    SANCTIONED_PARTY,
    BETTING_DESTINATION,
    DESTINATION_ACCOUNT_BLOCKED,
    NEW_DEVICE_LIMIT,
    NEW_DEVICE_STRUCTURING,
)
NOT_RELEASABLE_CODES = tuple(reason.code for reason in NOT_RELEASABLE)
