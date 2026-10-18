"""Contexto (4.2, seção 5.7 — teto 25, ρ = 0,3). Idade, profissão e renda não entram em sinal nenhum."""

from typing import Optional

from engine.evidence import Evidence, evidence
from engine.features import Features
from engine.measures import Measures
from engine.params import CONTEXT


def unusual_night(f: Features, m: Measures) -> Optional[Evidence]:
    """Noite fora do hábito: quem sempre usa à noite não é penalizado."""
    share = f.payer.baseline.night_out_share
    if m.is_night and (share is None or share < 0.10):
        return evidence("unusual_night", CONTEXT, 10)
    return None


def source_risk_history(f: Features, m: Measures) -> Optional[Evidence]:
    """Vítima recorrente ou conta comprometida."""
    baseline = f.payer.baseline
    points = (5 if baseline.account_block_count >= 1 else 0) + (5 if baseline.rejected_pix_out_count >= 1 else 0)

    if points:
        return evidence("source_risk_history", CONTEXT, points)
    return None


def dict_unavailable(f: Features, m: Measures) -> Optional[Evidence]:
    """Sem DICT recente, destino de outro banco e relação nova: não sabemos, então não aliviamos."""
    if not m.dict_recent and not f.destination.is_internal and f.relationship.previous_out_count == 0:
        return evidence("dict_unavailable", CONTEXT, 5)
    return None


def missing_geolocation(f: Features, m: Measures) -> Optional[Evidence]:
    """Sem localização do aparelho (IN 512, art. 3º, § 15). Fraco: o campo é opcional."""
    if (f.device.latitude is None or f.device.longitude is None) and not m.cold_start:
        return evidence("missing_geolocation", CONTEXT, 5)
    return None


SIGNALS = (unusual_night, source_risk_history, dict_unavailable, missing_geolocation)
