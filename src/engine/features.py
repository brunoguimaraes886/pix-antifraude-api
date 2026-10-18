"""O contrato entre a API e o motor: tudo que o motor recebe sobre um Pix.

A API monta um `Features` (src/controllers/feature_controller.py) e o
entrega ao motor. O motor não fala com banco, DICT nem HTTP: tudo que ele
precisa saber está aqui dentro. É isso que deixa o motor ser escrito e
testado sozinho, com features fixas (tests/unit/engine/).

O `Features` inteiro é gravado em `transaction_analysis.features` (JSONB),
então toda decisão fica auditável: dá pra ver exatamente o que o motor viu.

Convenções:
  • valores em centavos (int);
  • datas com fuso (datetime aware); no JSON, ISO 8601;
  • proporções como float; None quando a conta não fecha (divisão por zero,
    sem histórico) — "não sei" é diferente de 0.
"""

from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Union, get_args, get_origin, get_type_hints

# Situação da consulta ao DICT.
DICT_OK = "ok"                    # o DICT respondeu agora
DICT_FALLBACK = "fallback"        # não respondeu; veio da última análise do mesmo destino
DICT_UNAVAILABLE = "unavailable"  # não respondeu e não há análise anterior


@dataclass
class DictFeatures:
    status: str                     # DICT_OK, DICT_FALLBACK ou DICT_UNAVAILABLE
    response: Optional[dict]        # a resposta do DICT como veio (ou a do fallback)
    fetched_at: Optional[datetime]  # quando essa resposta foi consultada


@dataclass
class CustomerFeatures:
    document_type: str              # "PF" (CPF) ou "PJ" (CNPJ)
    age_years: int                  # PF: idade da pessoa; PJ: anos desde a fundação


@dataclass
class BaselineFeatures:
    """O resumo diário (account_baseline): o habitual dos últimos 30 dias."""

    baseline_date: date
    history_days: int               # dias da janela em que a conta já existia (0 a 30)
    avg_out_amount: Optional[int]
    p90_out_amount: Optional[int]
    avg_in_amount: Optional[int]
    p90_in_amount: Optional[int]
    avg_daily_out_count: Optional[float]
    avg_daily_in_count: Optional[float]
    account_block_count: int        # bloqueios da própria conta, todo o histórico
    rejected_pix_out_count: int     # Pix rejeitados por suspeita em que a conta pagava
    rejected_pix_in_count: int      # Pix rejeitados por suspeita em que a conta recebia
    night_out_share: Optional[float] = None  # fração dos Pix de saída no período noturno


@dataclass
class FlowSideFeatures:
    """Um sentido (entrada ou saída) de uma janela do extrato."""

    amount: int
    count: int
    distinct_counterparties: int
    new_counterparties: int         # nunca apareceram no extrato antes da janela
    repeated_counterparties: int    # aparecem 2+ vezes dentro da janela


@dataclass
class FlowWindowFeatures:
    """O que entrou e saiu da conta numa janela [start, end)."""

    start: datetime
    end: datetime
    balance_at_start: int
    inflow: FlowSideFeatures
    outflow: FlowSideFeatures
    pass_through_rate: Optional[float]  # saída / entrada
    exit_ratio: Optional[float]         # saída / (saldo no início + entrada)


@dataclass
class PeriodFeatures(FlowWindowFeatures):
    """Uma janela que é um período do relógio (diurno ou noturno)."""

    kind: str                       # "day" (6h–20h) ou "night" (20h–6h)
    is_current: bool                # True: o período em que o Pix caiu (até o Pix)
    limit: int                      # daily_limit no diurno, nightly_limit no noturno


@dataclass
class InternalAccountFeatures:
    """Uma conta nossa: perfil, saldo, limites, habitual e fluxo recente."""

    account_key: str
    customer: CustomerFeatures
    account_age_days: int
    balance: int                    # saldo antes deste Pix
    daily_limit: int
    nightly_limit: int
    is_blocked: bool                # bloqueio da conta em vigor no momento do Pix
    baseline: BaselineFeatures
    last_24h: FlowWindowFeatures
    current_period: PeriodFeatures
    previous_period: PeriodFeatures
    restricted_list: Optional[str] = None   # "csnu", "bets", "court_order" ou None
    # Só no pagador (no destino ficam 0): o limite do aparelho não cadastrado.
    unregistered_amount_today: int = 0      # aprovado hoje de aparelhos não cadastrados
    unregistered_near_limit_24h: int = 0    # Pix de R$ 180–200 de aparelho não cadastrado em 24h
    # Só no pagador: o DICT da própria conta, consultado uma vez por dia
    # (no resumo diário). None = não consultado; status unavailable = sem resposta hoje.
    dict: Optional[DictFeatures] = None


@dataclass
class DestinationHistoryFeatures:
    """Tudo que já chegou no nosso banco com esta conta como destino."""

    total_count: int
    approved_count: int
    two_factor_count: int
    rejected_count: int
    approved_amount: int
    distinct_payers: int            # clientes nossos distintos que já tentaram pagar
    first_seen_at: Optional[datetime]
    last_seen_at: Optional[datetime]
    last_24h_count: int
    last_24h_distinct_payers: int
    last_24h_approved_amount: int
    # Outros pagadores nossos cujo primeiro Pix para este destino (conta ou
    # CPF/CNPJ) foi nos últimos 7 dias: o fan-in.
    new_payers_7d: int = 0
    # Outros pagadores com Pix para este destino rejeitado por suspeita
    # sobre o destino nos últimos 90 dias (conta ou CPF/CNPJ).
    fraud_rejected_payers_90d: int = 0


@dataclass
class DestinationFeatures:
    is_internal: bool               # mesmo ISPB que o nosso
    participant: str
    document_type: str
    account_age_days: int           # externa: opening_date do payload; nossa: do banco
    account: Optional[InternalAccountFeatures]  # só quando a conta é nossa
    history: DestinationHistoryFeatures
    dict: Optional[DictFeatures]    # preenchido pelo motor; vazio se ele parou antes do DICT
    restricted_list: Optional[str] = None   # "csnu", "bets", "court_order" ou None


@dataclass
class RelationshipFeatures:
    """O pagador já conhece este destino?"""

    previous_out_count: int         # Pix aprovados do pagador para este destino
    previous_out_amount: int
    max_previous_out_amount: Optional[int]
    first_out_at: Optional[datetime]
    last_out_at: Optional[datetime]
    out_days_last_30d: int          # dias distintos com Pix para este destino
    previous_in_count: int          # o destino já pagou o pagador
    previous_attempts: int          # tentativas para este destino, qualquer decisão
    same_owner: bool = False        # destino com o mesmo CPF/CNPJ do pagador
    previous_in_amount: int = 0     # quanto o destino já pagou ao pagador
    first_in_at: Optional[datetime] = None
    # Últimas 24h, para este destino, sem as recusas operacionais:
    attempts_to_destination_24h: int = 0
    last_attempt_amount: Optional[int] = None
    blocked_attempts_24h: int = 0   # 2FA ou rejeitado por motivo do motor que não é só limite
    fraud_rejections_24h: int = 0   # rejeitado por suspeita (por conta ou CPF/CNPJ do destino)
    # Nas últimas 24h entrou, de uma contraparte nova e diferente do destino,
    # um valor a ±5% deste Pix (o golpe do "Pix errado").
    matching_recent_inflow: bool = False


@dataclass
class DeviceFeatures:
    device_id: str
    channel: str
    ip: str
    device_previous_uses: int       # Pix anteriores do pagador com este aparelho
    device_previous_approved_uses: int
    device_first_seen_at: Optional[datetime]
    ip_previous_uses: int
    distinct_devices_last_30d: int
    latitude: Optional[float]
    longitude: Optional[float]
    distance_from_last_km: Optional[float]      # do último Pix com localização
    minutes_since_last_location: Optional[float]
    approved_devices_count: int = 0             # aparelhos distintos com Pix aprovado nesta conta
    approved_days: int = 0                      # dias distintos com Pix aprovado deste aparelho
    first_approved_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None     # último Pix deste aparelho nesta conta
    other_accounts_last_30d: int = 0            # outras contas nossas que usaram este aparelho
    channel_previous_uses: int = 0              # Pix anteriores da conta pelo mesmo canal


@dataclass
class VelocityFeatures:
    """Tentativas do pagador, qualquer decisão (2FA e rejeitado contam)."""

    attempts_last_1h: int
    attempts_last_24h: int
    attempts_current_period: int
    seconds_since_last_attempt: Optional[float]


@dataclass
class TransactionFeatures:
    pix_id: str
    amount: int
    transaction_date: datetime
    local_hour: int                 # hora no fuso da transação
    weekday: int                    # 0 = segunda ... 6 = domingo
    period: str                     # "day" ou "night"
    ratio_to_balance: Optional[float]
    ratio_to_avg_out: Optional[float]
    ratio_to_p90_out: Optional[float]


@dataclass
class Features:
    transaction: TransactionFeatures
    payer: InternalAccountFeatures
    destination: DestinationFeatures
    relationship: RelationshipFeatures
    device: DeviceFeatures
    velocity: VelocityFeatures

    def to_dict(self) -> dict:
        """O Features em tipos de JSON — é o que vai para o banco."""
        return _to_jsonable(asdict(self))

    @staticmethod
    def from_dict(data: dict) -> "Features":
        """O caminho de volta: monta um Features a partir do JSON gravado.

        Serve para reproduzir uma decisão antiga no motor, e para escrever
        cenários de teste em JSON.
        """
        return _from_dict(Features, data)


def _to_jsonable(value):
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return float(value)

    return value


def _from_dict(cls, data: dict):
    hints = get_type_hints(cls)
    values = {}

    for field in fields(cls):
        values[field.name] = _convert(hints[field.name], data.get(field.name))

    return cls(**values)


def _convert(field_type, value):
    if value is None:
        return None

    if get_origin(field_type) is Union:
        not_none = [arg for arg in get_args(field_type) if arg is not type(None)]
        return _convert(not_none[0], value)

    if is_dataclass(field_type):
        return _from_dict(field_type, value)

    if field_type is datetime and isinstance(value, str):
        return datetime.fromisoformat(value)

    if field_type is date and isinstance(value, str):
        return date.fromisoformat(value)

    if field_type is float and isinstance(value, int):
        return float(value)

    return value
