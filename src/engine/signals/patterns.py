"""Assinaturas: o padrão completo de um golpe (4.2, seção 6 — teto 40).

O score trata os sinais como independentes, o que subestima as
combinações raras. Estas regras somam um bônus quando o padrão inteiro
aparece. Cada uma carrega o ρ da ameaça que representa.
"""

from typing import Optional, Set

from engine.evidence import Evidence, evidence
from engine.features import Features
from engine.measures import Measures
from engine.params import PATTERN
from engine.signals.payer_mule import payer_pass_through_points


def _share(m: Measures) -> float:
    return m.balance_share or 0.0


def scam_drain_pattern(f: Features, m: Measures, fired: Set[str]) -> Optional[Evidence]:
    """Falsa central, falso parente, extorsão: esvazia a conta para um destino novo ou suspeito."""
    if (
        m.first_payment
        and not m.same_owner
        and "payer_pass_through" not in fired
        and _share(m) >= 0.8
        and (m.destination_age_days < 90 or m.fan_in >= 2)
    ):
        return evidence("scam_drain_pattern", PATTERN, 20, rho=0.2)
    return None


def safe_account_pattern(f: Features, m: Measures, fired: Set[str]) -> Optional[Evidence]:
    """"Conta segura": conta própria nova recebendo boa parte do saldo."""
    if m.same_owner and m.destination_age_days < 30 and _share(m) >= 0.5:
        return evidence("safe_account_pattern", PATTERN, 20, rho=0.2)
    return None


def refund_to_third_party(f: Features, m: Measures, fired: Set[str]) -> Optional[Evidence]:
    """"Pix errado": devolve a um terceiro o valor que acabou de entrar."""
    if f.relationship.matching_recent_inflow and m.first_payment:
        return evidence("refund_to_third_party", PATTERN, 20, rho=0.2)
    return None


def scam_ladder(f: Features, m: Measures, fired: Set[str]) -> Optional[Evidence]:
    """Investimento, amor, tarefas: valores crescentes para conta nova."""
    if m.escalating and m.destination_age_days < 180:
        return evidence("scam_ladder", PATTERN, 15, rho=0.2)
    return None


def takeover_cashout(f: Features, m: Measures, fired: Set[str]) -> Optional[Evidence]:
    """Roubo de usuário: aparelho não cadastrado, destino novo e valor alto."""
    if not m.device_registered and m.first_payment and (m.amount_ratio >= 3 or _share(m) >= 0.5):
        return evidence("takeover_cashout", PATTERN, 15, rho=0.9)
    return None


def night_coercion(f: Features, m: Measures, fired: Set[str]) -> Optional[Evidence]:
    """Roubo noturno, sequestro: vários destinos novos à noite, esvaziando a conta."""
    if m.is_night and m.new_payees_period >= 2 and (m.exit_ratio_with_pix or 0) >= 0.5:
        return evidence("night_coercion", PATTERN, 25, rho=0.4)
    return None


def fresh_mule(f: Features, m: Measures, fired: Set[str]) -> Optional[Evidence]:
    """Laranja no destino: conta nova com fan-in, ou conta nossa de passagem."""
    factor = m.fan_in_factor
    new_with_fan_in = m.destination_age_days < 30 and m.fan_in >= 2 * factor and not m.same_owner

    internal_pass_through = False
    account = f.destination.account
    if account is not None and m.destination_pass_through is not None:
        internal_pass_through = (
            m.destination_pass_through >= 0.8
            and account.last_24h.inflow.new_counterparties >= 3 * factor
            and (m.destination_age_days < 90 or (m.destination_inflow_jump or 0) >= 3)
        )

    if new_with_fan_in or internal_pass_through:
        return evidence("fresh_mule", PATTERN, 30, rho=0.1)
    return None


def mule_cashout(f: Features, m: Measures, fired: Set[str]) -> Optional[Evidence]:
    """Laranja no pagador repassando para destino novo, com um terceiro elemento.

    O terceiro elemento separa a laranja do racha, da vaquinha e do autônomo
    que paga o fornecedor: esses ficam com `payer_pass_through` e o alerta
    de PLD, sem o bônus.
    """
    if not payer_pass_through_points(f, m) or not m.first_payment:
        return None

    third_element = (
        m.destination_age_days < 180
        or m.fan_in >= 2
        or bool(m.dict_markers)
        or m.payer_dormant
        or (m.payer_inflow_jump or 0) >= 10
    )

    if third_element:
        return evidence("mule_cashout", PATTERN, 25, rho=0.1)
    return None


SIGNALS = (
    scam_drain_pattern,
    safe_account_pattern,
    refund_to_third_party,
    scam_ladder,
    takeover_cashout,
    night_coercion,
    fresh_mule,
    mule_cashout,
)
