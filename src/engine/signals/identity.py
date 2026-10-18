"""Identidade: quem opera é o dono? (4.2, seção 5.1 — teto 50, ρ = 0,9)"""

from typing import Optional

from engine.evidence import Evidence, evidence
from engine.features import Features
from engine.measures import Measures
from engine.params import IDENTITY


def new_device(f: Features, m: Measures) -> Optional[Evidence]:
    """Na invasão de conta o aparelho novo aparece quase sempre."""
    if not m.device_registered:
        return evidence("new_device", IDENTITY, 25)
    return None


def new_ip(f: Features, m: Measures) -> Optional[Evidence]:
    """IP de celular muda o tempo todo (CGNAT): só conta junto com aparelho não cadastrado."""
    if f.device.ip_previous_uses == 0 and not m.device_registered:
        return evidence("new_ip", IDENTITY, 5)
    return None


def shared_device(f: Features, m: Measures) -> Optional[Evidence]:
    """Um celular operando 3+ contas: fazenda de laranjas ou golpista com várias vítimas."""
    if f.device.other_accounts_last_30d >= 3:
        return evidence("shared_device", IDENTITY, 20)
    return None


def new_channel(f: Features, m: Measures) -> Optional[Evidence]:
    """Conta que já faz Pix aparece por um canal que nunca usou (fora do cold start)."""
    if f.device.channel_previous_uses == 0 and m.n_out > 0 and not m.cold_start:
        return evidence("new_channel", IDENTITY, 5)
    return None


def location(f: Features, m: Measures) -> Optional[Evidence]:
    """Distância do último Pix com localização; a viagem impossível substitui a distância."""
    distance = f.device.distance_from_last_km
    if distance is None:
        return None

    if m.speed_kmh is not None and m.speed_kmh > 900 and distance > 100:
        return evidence("impossible_travel", IDENTITY, 25)

    if distance > 1000:
        return evidence("far_from_last_location", IDENTITY, 15)

    if distance > 200:
        return evidence("far_from_last_location", IDENTITY, 10)

    return None


SIGNALS = (new_device, new_ip, shared_device, new_channel, location)
