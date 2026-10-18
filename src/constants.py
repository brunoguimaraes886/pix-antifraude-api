import os


SERVICE_ROOT = os.path.abspath(os.path.dirname(__file__))

# Onde moram os arquivos de schema (src/schemas/), lidos pelo
# src/utils/schema_handler.py.
SCHEMA_PATH = os.path.join(SERVICE_ROOT, "schemas")

APP_ENV = os.environ.get("APP_ENV", "local")
SERVICE_NAME = os.environ.get("SERVICE_NAME", "pix-antifraude-api")

DATABASE_URL = os.environ.get("DATABASE_URL")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN")

# O DICT do Banco Central (no projeto, um mock server). Prazo curto: o Pix
# precisa ser decidido em poucos segundos, e o DICT que não responde a
# tempo é substituído pela última consulta do mesmo destino.
DICT_API_URL = os.environ.get("DICT_API_URL", "http://localhost:1080/dict")
DICT_API_INTERNAL_TOKEN = os.environ.get("DICT_API_INTERNAL_TOKEN", "default_token")
DICT_API_TIMEOUT = float(os.environ.get("DICT_API_TIMEOUT", "1"))

# ────────────────────────────────────────────────────────────────
# Regras fixas do negócio
# ────────────────────────────────────────────────────────────────

# O nosso ISPB. Destino com este ISPB é conta nossa: tem perfil, extrato
# e resumo diário. Qualquer outro é conta de outro banco.
OUR_ISPB = "88888888"

# Janela do resumo diário do histórico (account_baseline).
BASELINE_WINDOW_DAYS = 30

# Períodos do dia, no fuso da própria transação: diurno das 6h às 22h,
# noturno das 22h às 6h. Cada um tem o seu limite na conta.
DAY_PERIOD_START_HOUR = 6
NIGHT_PERIOD_START_HOUR = 22

# Rotas públicas: não exigem o header INTERNAL-TOKEN.
BYPASS_ENDPOINTS = [
    "/",
    "/health_check",
]

REQUIRED_VARIABLES = ["DATABASE_URL", "INTERNAL_TOKEN"]


def check_variables():
    missing = []
    for name in REQUIRED_VARIABLES:
        if not globals().get(name):
            missing.append(name)

    if missing:
        raise EnvironmentError(
            f"Faltam variáveis de ambiente: {', '.join(missing)}. "
            "Rodando com 'docker compose up' elas já vêm preenchidas. "
            "Fora do Docker, copie o .env.example para .env."
        )
