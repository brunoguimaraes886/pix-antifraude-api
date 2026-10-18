"""Todos os pesos, limiares e custos do motor num lugar só (4.2, seção 14).

É aqui que se calibra a política sem mexer no motor. Valores em centavos,
como o resto do `Features`; V (o valor do Pix na política de custo) entra
em reais.

Os pontos são premissas de especialista na escala de log-odds: +10 pontos
= chance de fraude 2× maior. Em produção, cada um se recalcula pelo retorno
do MED: pontos = 10 · log2(LR).
"""

# ── Escala e prior (seção 7) ─────────────────────────────────────

PDO = 10                    # pontos para dobrar a chance de fraude
PRIOR_ODDS = 1 / 10_000     # 1 fraude a cada 10.000 Pix enviados

# ── Famílias: (teto de pontos, ρ = eficácia do 2FA) (seção 5) ─────

IDENTITY = "identity"
MAGNITUDE = "magnitude"
VELOCITY = "velocity"
RELATIONSHIP = "relationship"
DESTINATION = "destination"
PAYER_MULE = "payer_mule"
CONTEXT = "context"
PATTERN = "pattern"

FAMILIES = {
    IDENTITY: (50, 0.9),
    MAGNITUDE: (40, 0.4),
    VELOCITY: (40, 0.4),
    RELATIONSHIP: (30, 0.3),
    DESTINATION: (80, 0.1),
    PAYER_MULE: (60, 0.1),
    CONTEXT: (25, 0.3),
    PATTERN: (40, None),    # assinaturas: o ρ vem de cada uma
}

MITIGATION_FLOOR = -40      # soma mínima dos mitigantes (pontos negativos)

# ── Política de custo (seção 8) ──────────────────────────────────

C_2FA = 3.0                 # R$: atrito de pedir confirmação a um cliente legítimo
C_REJECT = 20.0             # R$: custo fixo de barrar um legítimo (só na derivação dos cortes)
ALPHA = 0.10                # parte proporcional ao valor de barrar um legítimo (idem)
P_FUNDADA_SUSPEITA = 0.10   # a partir daqui, rejeita (salvo ameaça de identidade)
P_RISCO_CLARO = 0.50        # a partir daqui, rejeita sempre
RHO_IDENTITY = 0.5          # ρ a partir do qual a ameaça é de identidade (o 2FA resolve)

# ── Perfil padrão sem histórico (credibilidade de Bühlmann, seção 4.1) ─

K_PRIOR = 10                # Pix de "peso" do perfil padrão
P90_PRIOR = 50_000          # R$ 500: p90 de saída de quem não tem histórico
DAILY_COUNT_PRIOR = 1.0     # Pix por dia de quem não tem histórico
INFLOW_JUMP_FLOOR = 50_000  # R$ 500: piso do mês anterior em inflow_jump
FULL_HISTORY_DAYS = 30      # inflow_jump e dormência só com a janela inteira

# ── Aparelho não cadastrado (IN BCB 491/2024) ─────────────────────

NEW_DEVICE_MAX_PIX = 20_000         # R$ 200 por Pix
NEW_DEVICE_MAX_DAY = 100_000        # R$ 1.000 por dia, somando todos os não cadastrados
NEAR_LIMIT_MIN = 18_000             # R$ 180: faixa do fracionamento
DEVICE_KNOWN_DAYS = 3               # dias distintos com Pix aprovado
DEVICE_KNOWN_MIN_AGE_DAYS = 7       # o primeiro aprovado há pelo menos 7 dias
DEVICE_EXPIRY_DAYS = 365            # sem uso há mais de 12 meses, deixa de ser cadastrado
COLD_START_ACCOUNT_DAYS = 7         # aparelho do onboarding

# ── DICT ─────────────────────────────────────────────────────────

DICT_HARD_DAYS = 365                # marcação "recente" (rejeição e peso cheio)
DICT_VALID_DAYS = 1825              # marcação ainda válida (5 anos)
DICT_STALE_HOURS = 24               # fallback mais velho que isto = sem DICT recente
DICT_HARD_TYPES = ("MULE_ACCOUNT", "SCAMMER_ACCOUNT")
DICT_FLOOR_TYPES = DICT_HARD_TYPES + ("APPLICATION_FRAUD",)
DICT_REINFORCEMENT_ACCOUNT_DAYS = 90    # reforço: conta destino nova
DICT_REINFORCEMENT_FAN_IN = 2           # reforço: vários pagadores novos

# ── Destino ──────────────────────────────────────────────────────

PJ_FAN_IN_FACTOR = 3        # PJ recebe de muita gente: limiares de fan-in × 3

# ── Janelas (em horas/dias, usadas pela API ao montar o Features) ─

WINDOW_24H_HOURS = 24
FAN_IN_DAYS = 7
DESTINATION_REJECTIONS_DAYS = 90
SHARED_DEVICE_DAYS = 30
MATCHING_INFLOW_TOLERANCE = 0.05    # ±5% (refund_to_third_party)
