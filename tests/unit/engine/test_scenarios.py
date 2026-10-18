"""Os cenários da seção 10 do 4.2: legítimos difíceis (L) e golpes (G).

Cada cenário monta o `Features` descrito no documento e confere a decisão.
Os pontos exatos dependem de como cada cenário é montado (o protótipo do
documento e estes testes não usam os mesmos números de perfil), por isso o
teste fixa a DECISÃO e, quando é o que o cenário quer mostrar, o motivo ou
a marca da camada interna (alerta de PLD, ameaça).

Valores em centavos. O perfil padrão do pagador (factory): saldo R$ 5.000,
p90 de saída R$ 400, 0,8 Pix por dia, 30 dias de histórico, conta de 600
dias, aparelho cadastrado.
"""

from datetime import timedelta

import pytest

from engine.features import DICT_UNAVAILABLE, DictFeatures
from engine.result import APPROVED, REJECTED, TWO_FACTOR_REQUIRED
from tests.unit.engine.engine_runner import codes, evaluate
from tests.unit.engine.features_factory import (
    MOMENT,
    at_night,
    clean_features,
    dict_answer,
    inflow_24h,
    internal_destination,
    limits,
    marker,
    new_destination,
    outflow_24h,
    paid_before,
    payer_profile,
    settle,
    unregistered_device,
)


def pix(amount: int):
    return clean_features(amount=amount)


# ── Legítimos difíceis ───────────────────────────────────────────


def l1_rent_recurring():
    f = payer_profile(pix(200000), balance=240000, p90=250000)
    paid_before(f, count=6, total=1200000, largest=200000, first_days_ago=180, last_days_ago=30)
    return settle(f)


def l2_new_friend():
    return settle(new_destination(pix(15000)))


def l3_first_rent():
    f = payer_profile(pix(250000), balance=300000, p90=250000)
    return settle(new_destination(f))


def l4_friend_new_account():
    return settle(new_destination(pix(10000), age_days=5))


def l5_car():
    f = payer_profile(pix(6000000), balance=6976744, p90=150000)
    limits(f, daily=10000000)
    return settle(new_destination(f))


def l6_travel():
    f = pix(10000)
    f.device.ip_previous_uses = 0
    f.device.distance_from_last_km = 1500
    f.device.minutes_since_last_location = 2 * 24 * 60
    return settle(f)


def l7_new_phone_usual_bill():
    f = pix(18000)
    paid_before(f, count=6, total=108000, largest=18000, first_days_ago=180, last_days_ago=30)
    return settle(unregistered_device(f))


def l8_freelancer_pays_usual_supplier():
    f = payer_profile(pix(400000), balance=450000, p90=400000, avg_in=70000, daily_in=0.2)
    paid_before(f, count=6, total=2400000, largest=400000, first_days_ago=180, last_days_ago=30)
    inflow_24h(f, 420000, new_counterparties=6)
    return settle(f)


def l9_crowdfunding_hospital():
    f = payer_profile(pix(400000), balance=450000, avg_in=150000, daily_in=0.07)
    inflow_24h(f, 400000, new_counterparties=10)
    return settle(new_destination(f, age_days=5000, document_type="PJ"))


def l10_salary_then_card():
    f = payer_profile(pix(150000), balance=800000, p90=150000)
    paid_before(f, count=6, total=900000, largest=160000, first_days_ago=180, last_days_ago=30)
    inflow_24h(f, 450000, new_counterparties=0, count=1)
    return settle(f)


def l11_own_account_other_bank():
    f = payer_profile(pix(700000), balance=777777, p90=300000)
    new_destination(f, age_days=2000)
    f.relationship.same_owner = True
    return settle(f)


def l12_company_new_supplier():
    f = payer_profile(pix(900000), balance=8000000, p90=1000000, document_type="PJ")
    limits(f, daily=5000000)
    return settle(new_destination(f, document_type="PJ"))


def l13_contractor_installments():
    f = payer_profile(pix(500000), balance=2000000, p90=300000)
    new_destination(f, age_days=1100)
    paid_before(f, count=2, total=300000, largest=200000, first_days_ago=20, last_days_ago=10)
    return settle(f)


def l14_split_the_bill():
    f = payer_profile(pix(240000), balance=300000)
    inflow_24h(f, 200000, new_counterparties=5)
    return settle(new_destination(f))


def l15_portability():
    f = payer_profile(pix(900000), balance=1000000)
    new_destination(f, age_days=2)
    f.relationship.same_owner = True
    return settle(f)


def l16_gift_to_friend_new_account():
    f = new_destination(pix(5000), age_days=5)
    f.destination.history.new_payers_7d = 2
    return settle(f)


def l17_retiree_first_pix():
    f = payer_profile(pix(15000), daily_out=0.0, p90=None)
    f.payer.baseline.avg_out_amount = None
    f.payer.account_age_days = 3650
    f.device.channel_previous_uses = 0
    unregistered_device(f, other_devices=0)
    return settle(new_destination(f))


def l18_restaurant_at_night():
    f = payer_profile(pix(150000), night_share=0.0)
    limits(f, daily=1000000, nightly=100000)
    at_night(f)
    return settle(new_destination(f, document_type="PJ"))


def l19_new_account_first_rent():
    f = payer_profile(pix(120000), balance=300000, p90=None, daily_out=None, daily_in=None, history_days=5, age_days=5)
    f.payer.baseline.avg_in_amount = None
    f.device.approved_devices_count = 0
    f.device.approved_days = 0
    f.device.first_approved_at = None
    inflow_24h(f, 300000, new_counterparties=1)
    return settle(new_destination(f))


# ── Golpes ───────────────────────────────────────────────────────


def g1_fake_call_center():
    f = payer_profile(pix(800000), balance=842105)
    return settle(new_destination(f, age_days=10))


def g2_fake_call_center_clean_destination():
    f = payer_profile(pix(800000), balance=842105)
    return settle(new_destination(f))


def g3_investment_ladder():
    f = payer_profile(pix(600000), balance=1500000, p90=300000)
    new_destination(f, age_days=60, document_type="PJ")
    paid_before(f, count=3, total=550000, largest=300000, first_days_ago=20, last_days_ago=3)
    return settle(f)


def g4_account_takeover():
    f = payer_profile(pix(500000), balance=909090, p90=125000)
    unregistered_device(f)
    return settle(new_destination(f))


def g4b_warmed_device():
    f = unregistered_device(pix(100000), approved_days=1, ip_known=True)
    return settle(new_destination(f))


def g5_night_robbery():
    f = payer_profile(pix(150000), balance=300000, night_share=0.0)
    limits(f, nightly=500000)
    at_night(f)
    outflow_24h(f, 300000, count=2, new_counterparties=2)
    return settle(new_destination(f))


def g6_external_mule():
    f = new_destination(pix(20000), age_days=3)
    f.destination.history.new_payers_7d = 4
    return settle(f)


def g7_dict_mule_new_account():
    f = new_destination(pix(10000), age_days=60)
    return settle(dict_answer(f, account=[marker("MULE_ACCOUNT", 240)]))


def g7a_dict_mule_old_account():
    f = new_destination(pix(10000), age_days=1100)
    return settle(dict_answer(f, account=[marker("MULE_ACCOUNT", 240)]))


def g7b_dict_old_scammer():
    f = new_destination(pix(10000), age_days=1100)
    return settle(dict_answer(f, owner=[marker("SCAMMER_ACCOUNT", 730)]))


def g7c_dict_application_fraud():
    f = new_destination(pix(10000), age_days=1100)
    return settle(dict_answer(f, owner=[marker("APPLICATION_FRAUD", 100)]))


def g8_internal_constant_mule():
    f = new_destination(pix(50000), age_days=60)
    account = internal_destination(f, age_days=60)
    window = account.last_24h
    window.inflow.amount, window.inflow.count, window.inflow.new_counterparties = 450000, 3, 3
    window.outflow.amount, window.outflow.count = 430000, 3
    window.pass_through_rate = 430000 / 450000
    # Constante: entra o mesmo todo dia desde que abriu, então não há salto.
    account.baseline.avg_in_amount, account.baseline.avg_daily_in_count = 150000, 3.0
    return settle(f)


def g9_safe_account():
    f = payer_profile(pix(1200000), balance=1333333)
    limits(f, daily=2000000)
    new_destination(f, age_days=2)
    f.relationship.same_owner = True
    return settle(f)


def g10_wrong_pix_refund():
    f = new_destination(pix(150000), age_days=20)
    inflow_24h(f, 150000, new_counterparties=1)
    f.relationship.matching_recent_inflow = True
    return settle(f)


def g11_payer_mule():
    f = payer_profile(pix(880000), balance=950000, p90=30000, avg_in=24000, daily_in=1 / 6, age_days=40)
    inflow_24h(f, 900000, new_counterparties=5)
    return settle(new_destination(f, age_days=120))


def g12_love_scam_ladder():
    f = payer_profile(pix(300000), balance=1000000)
    new_destination(f, age_days=100)
    paid_before(f, count=4, total=600000, largest=250000, first_days_ago=30, last_days_ago=5)
    return settle(f)


def g12b_long_love_scam():
    f = payer_profile(pix(800000), balance=2000000)
    new_destination(f, age_days=1100)
    paid_before(f, count=10, total=1500000, largest=200000, first_days_ago=100, last_days_ago=7)
    return settle(f)


def g13_structuring_new_device():
    f = unregistered_device(pix(19900))
    f.payer.unregistered_near_limit_24h = 1
    return settle(new_destination(f))


def g14_dormant_account_wakes_up():
    f = payer_profile(pix(380000), balance=400000, p90=None, daily_out=0.03, daily_in=0.03, avg_in=10000, age_days=2000)
    inflow_24h(f, 400000, new_counterparties=4)
    return settle(new_destination(f))


def g15_shared_device():
    f = unregistered_device(pix(200000), ip_known=True)
    f.device.other_accounts_last_30d = 3
    return settle(new_destination(f))


def g16_insists_after_rejection():
    f = payer_profile(pix(300000), balance=500000)
    new_destination(f, age_days=15)
    f.relationship.fraud_rejections_24h = 1
    f.relationship.blocked_attempts_24h = 1
    return settle(f)


def g16a_original_attempt():
    f = payer_profile(pix(500000), balance=500000)
    return settle(new_destination(f, age_days=15))


def g17_insists_after_2fa():
    f = payer_profile(pix(300000), balance=500000)
    new_destination(f, age_days=15)
    f.relationship.blocked_attempts_24h = 1
    f.relationship.attempts_to_destination_24h = 1
    f.relationship.last_attempt_amount = 500000
    return settle(f)


def g18_destination_rejected_with_others():
    f = new_destination(pix(100000), age_days=45)
    f.destination.history.fraud_rejected_payers_90d = 2
    return settle(f)


def g19_betting():
    f = new_destination(pix(30000), document_type="PJ")
    f.destination.restricted_list = "bets"
    return settle(f)


def g20_test_then_large():
    f = payer_profile(pix(400000), balance=2000000)
    new_destination(f, age_days=20)
    paid_before(f, count=1, total=100, largest=100, first_days_ago=10 / (24 * 60))
    return settle(f)


def g21_slow_ladder():
    f = payer_profile(pix(270000), balance=1500000)
    new_destination(f, age_days=200)
    paid_before(f, count=6, total=900000, largest=200000, first_days_ago=40, last_days_ago=5)
    return settle(f)


SCENARIOS = [
    ("L1", l1_rent_recurring, APPROVED),
    ("L2", l2_new_friend, APPROVED),
    ("L3", l3_first_rent, APPROVED),
    ("L4", l4_friend_new_account, APPROVED),
    ("L5", l5_car, TWO_FACTOR_REQUIRED),
    ("L6", l6_travel, APPROVED),
    ("L7", l7_new_phone_usual_bill, APPROVED),
    ("L8", l8_freelancer_pays_usual_supplier, APPROVED),
    ("L9", l9_crowdfunding_hospital, TWO_FACTOR_REQUIRED),
    ("L10", l10_salary_then_card, APPROVED),
    ("L11", l11_own_account_other_bank, APPROVED),
    ("L12", l12_company_new_supplier, APPROVED),
    ("L13", l13_contractor_installments, APPROVED),
    ("L14", l14_split_the_bill, TWO_FACTOR_REQUIRED),
    ("L15", l15_portability, TWO_FACTOR_REQUIRED),
    ("L16", l16_gift_to_friend_new_account, APPROVED),
    ("L17", l17_retiree_first_pix, APPROVED),
    ("L18", l18_restaurant_at_night, APPROVED),
    ("L19", l19_new_account_first_rent, APPROVED),
    ("G1", g1_fake_call_center, REJECTED),
    ("G2", g2_fake_call_center_clean_destination, TWO_FACTOR_REQUIRED),
    ("G3", g3_investment_ladder, TWO_FACTOR_REQUIRED),
    ("G4", g4_account_takeover, TWO_FACTOR_REQUIRED),
    ("G4b", g4b_warmed_device, TWO_FACTOR_REQUIRED),
    ("G5", g5_night_robbery, TWO_FACTOR_REQUIRED),
    ("G6", g6_external_mule, REJECTED),
    ("G7", g7_dict_mule_new_account, REJECTED),
    ("G7a", g7a_dict_mule_old_account, TWO_FACTOR_REQUIRED),
    ("G7b", g7b_dict_old_scammer, TWO_FACTOR_REQUIRED),
    ("G7c", g7c_dict_application_fraud, TWO_FACTOR_REQUIRED),
    ("G8", g8_internal_constant_mule, TWO_FACTOR_REQUIRED),
    ("G9", g9_safe_account, TWO_FACTOR_REQUIRED),
    ("G10", g10_wrong_pix_refund, TWO_FACTOR_REQUIRED),
    ("G11", g11_payer_mule, REJECTED),
    ("G12", g12_love_scam_ladder, TWO_FACTOR_REQUIRED),
    ("G12b", g12b_long_love_scam, TWO_FACTOR_REQUIRED),
    ("G13", g13_structuring_new_device, TWO_FACTOR_REQUIRED),
    ("G14", g14_dormant_account_wakes_up, REJECTED),
    ("G15", g15_shared_device, TWO_FACTOR_REQUIRED),
    ("G16", g16_insists_after_rejection, REJECTED),
    ("G16a", g16a_original_attempt, REJECTED),
    ("G17", g17_insists_after_2fa, TWO_FACTOR_REQUIRED),
    ("G18", g18_destination_rejected_with_others, TWO_FACTOR_REQUIRED),
    ("G19", g19_betting, REJECTED),
    ("G20", g20_test_then_large, TWO_FACTOR_REQUIRED),
    ("G21", g21_slow_ladder, APPROVED),
]


@pytest.mark.parametrize("name,build,expected", SCENARIOS, ids=[name for name, _, _ in SCENARIOS])
def test_scenario_decision(name, build, expected):
    result = evaluate(build())

    assert result.status == expected, (name, result.score, result.decision.get("probability"), codes(result))


class TestWhatEachScenarioShows:
    """O motivo de cada cenário, além da decisão."""

    def test_l8_freelancer_raises_pld_alert_without_blocking(self):
        result = evaluate(l8_freelancer_pays_usual_supplier())

        assert result.status == APPROVED
        assert result.decision["pld_alert"] is True

    def test_l9_and_l14_have_no_mule_cashout_without_a_third_element(self):
        for build in (l9_crowdfunding_hospital, l14_split_the_bill):
            result = evaluate(build())
            assert "mule_cashout" not in codes(result)
            assert result.decision["pld_alert"] is True

    def test_l15_and_g9_get_the_safe_account_alert(self):
        for build in (l15_portability, g9_safe_account):
            result = evaluate(build())
            assert "safe_account_pattern" in codes(result)
            assert "conta segura" in result.alert
            assert result.hold_recommended is True

    def test_l18_night_limit_is_only_between_people(self):
        result = evaluate(l18_restaurant_at_night())

        assert "limit_exceeded" not in codes(result)
        assert result.decision["effective_limit"] == 1000000

    def test_g1_is_founded_suspicion_of_scam(self):
        result = evaluate(g1_fake_call_center())

        assert result.decision["rule"] == "fundada_suspeita"
        assert result.decision["situation_type"] == "SCAM"
        assert "scam_drain_pattern" in codes(result)

    def test_g2_scam_without_destination_signals_asks_and_holds(self):
        result = evaluate(g2_fake_call_center_clean_destination())

        assert result.hold_recommended is True
        assert result.alert is not None

    def test_g4_takeover_is_identity(self):
        result = evaluate(g4_account_takeover())

        assert result.decision["threat"] == "identidade"
        assert "new_device_limit" in codes(result)
        assert result.hold_recommended is False

    def test_g6_rejects_a_mule_even_at_a_low_amount(self):
        result = evaluate(g6_external_mule())

        assert "fresh_mule" in codes(result)
        assert result.decision["threat"] == "laranja"
        assert result.decision["destination_evidence"] is True

    def test_g7_family(self):
        assert codes(evaluate(g7_dict_mule_new_account()))[0] == "dict_fraud_marker"
        for build in (g7a_dict_mule_old_account, g7b_dict_old_scammer, g7c_dict_application_fraud):
            assert codes(evaluate(build()))[0] == "dict_marker"

    def test_g7_rejection_only_on_third_party_mark_is_recorded(self):
        result = evaluate(g7_dict_mule_new_account())

        assert result.decision["basis"] == "third_party_mark"

    def test_g8_constant_mule_only_gets_2fa_with_hold(self):
        result = evaluate(g8_internal_constant_mule())

        assert "fresh_mule" in codes(result)
        assert result.hold_recommended is True

    def test_g11_payer_mule_is_rejected_with_pld_alert(self):
        result = evaluate(g11_payer_mule())

        assert "mule_cashout" in codes(result)
        assert result.decision["pld_alert"] is True

    def test_g13_structuring_raises_pld_alert(self):
        result = evaluate(g13_structuring_new_device())

        assert codes(result)[0] == "new_device_structuring"
        assert result.decision["pld_alert"] is True

    def test_g16_insistence_stops_before_the_dict(self):
        from tests.unit.engine.engine_runner import FakeDict

        features = g16_insists_after_rejection()
        fake_dict = FakeDict(features)
        result = evaluate(features, fake_dict)

        assert codes(result) == ["repeat_after_fraud_rejection"]
        assert fake_dict.calls == 0

    def test_g17_retry_after_2fa(self):
        assert "retry_after_block" in codes(evaluate(g17_insists_after_2fa()))

    def test_g20_test_then_large(self):
        assert "test_then_large" in codes(evaluate(g20_test_then_large()))


def test_dict_unavailable_for_a_new_external_destination_asks_for_2fa():
    f = new_destination(pix(10000))
    f.destination.dict = DictFeatures(status=DICT_UNAVAILABLE, response=None, fetched_at=None)

    result = evaluate(settle(f))

    assert result.status == TWO_FACTOR_REQUIRED
    assert codes(result)[0] == "dict_unavailable"


def test_stale_fallback_counts_as_no_recent_dict():
    f = new_destination(pix(10000))
    f.destination.dict = DictFeatures(
        status="fallback",
        response={"account": {"fraud_markers": []}, "owner": {"fraud_markers": []}},
        fetched_at=MOMENT - timedelta(hours=25),
    )

    assert codes(evaluate(settle(f)))[0] == "dict_unavailable"
