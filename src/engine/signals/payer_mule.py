"""Pagador como laranja: está repassando dinheiro de outros? (4.2, seção 5.6 — teto 60, ρ = 0,1)

Todos os motivos daqui são sensíveis a PLD: na resposta pública viram
`risk_policy`.
"""

from typing import Optional

from engine.evidence import Evidence, evidence
from engine.features import Features
from engine.measures import Measures
from engine.params import PAYER_MULE


def payer_pass_through_points(f: Features, m: Measures) -> int:
    """Recebe de vários desconhecidos e repassa quase tudo (Carta Circular 4.001, IV-k, IV-ad)."""
    inflow = f.payer.last_24h.inflow

    if (
        inflow.new_counterparties >= 2
        and m.pass_through_with_pix is not None
        and m.pass_through_with_pix >= 0.8
        and inflow.amount >= m.amount / 2
    ):
        return 30 if inflow.new_counterparties >= 4 else 20

    return 0


def payer_pass_through(f: Features, m: Measures) -> Optional[Evidence]:
    points = payer_pass_through_points(f, m)
    if points:
        return evidence("payer_pass_through", PAYER_MULE, points)
    return None


def new_source_account(f: Features, m: Measures) -> Optional[Evidence]:
    """Conta nova repassando. Sozinha, idade da conta não soma (cold start)."""
    if payer_pass_through_points(f, m) and f.payer.account_age_days < 30:
        return evidence("new_source_account", PAYER_MULE, 10)
    return None


def payer_inflow_jump(f: Features, m: Measures) -> Optional[Evidence]:
    """Entrou num dia muito mais do que costuma entrar num mês (IV-a)."""
    jump = m.payer_inflow_jump
    if jump is None:
        return None

    if jump >= 10:
        return evidence("payer_inflow_jump", PAYER_MULE, 20)
    if jump >= 3:
        return evidence("payer_inflow_jump", PAYER_MULE, 10)
    return None


def payer_dormant_awakened(f: Features, m: Measures) -> Optional[Evidence]:
    """Conta parada que volta a movimentar de repente (IV-e)."""
    if m.payer_dormant and f.payer.last_24h.inflow.count >= 2:
        return evidence("payer_dormant_awakened", PAYER_MULE, 15)
    return None


SIGNALS = (payer_pass_through, new_source_account, payer_inflow_jump, payer_dormant_awakened)
