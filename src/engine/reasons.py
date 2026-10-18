"""O catálogo de motivos. Todo motivo que sai na resposta nasce aqui.

O `code` é o contrato (quem integra programa em cima dele); a `message` é
para gente ler. Motivo novo do motor entra no fim deste arquivo.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Reason:
    code: str
    message: str


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

# O motor quebrou: o Pix não sai sem confirmação (fail-safe).
ENGINE_ERROR = Reason("engine_error", "O motor antifraude falhou; o Pix precisa de confirmação.")


# ────────────────────────────────────────────────────────────────
# Do motor
# ────────────────────────────────────────────────────────────────

LIMIT_EXCEEDED = Reason("limit_exceeded", "O Pix passa do limite do período (diurno ou noturno).")
DICT_FRAUD_MARKER = Reason("dict_fraud_marker", "A conta ou o CPF/CNPJ de destino tem marcação de fraude no DICT.")
DICT_UNAVAILABLE = Reason("dict_unavailable", "O DICT não respondeu e não há consulta anterior deste destino.")
