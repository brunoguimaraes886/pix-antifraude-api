"""Regras duras, política, score e as propriedades do motor (4.2, seção 12)."""

import random
from datetime import timedelta

import pytest

from engine import params
from engine.evidence import Evidence
from engine.features import Features
from engine.policy import by_score, decide
from engine.reasons import PLD_SENSITIVE, Reason
from engine.response import public_reasons
from engine.result import APPROVED, REJECTED, SEVERITY, TWO_FACTOR_REQUIRED
from engine.scoring import probability, score
from tests.unit.engine.engine_runner import FakeDict, codes, evaluate
from tests.unit.engine.features_factory import (
    MOMENT,
    at_night,
    clean_features,
    dict_answer,
    inflow_24h,
    marker,
    new_destination,
    payer_profile,
    settle,
    unregistered_device,
)


class TestCleanPix:
    def test_clean_pix_is_approved_without_reasons(self):
        result = evaluate(clean_features())

        assert result.status == APPROVED
        assert result.decision["rule"] == "risco_baixo"

    def test_records_points_and_probability(self):
        result = evaluate(settle(new_destination(clean_features(15000))))

        assert result.score == 15
        assert result.decision["probability"] == pytest.approx(probability(15), rel=1e-3)


class TestHardRules:
    def test_limit_counts_what_already_left_in_the_period(self):
        features = clean_features(amount=30000)
        features.payer.daily_limit = 100000
        features.payer.current_period.outflow.amount = 80000

        result = evaluate(features)

        assert result.status == REJECTED
        assert codes(result) == ["limit_exceeded"]

    def test_exactly_at_the_limit_passes_the_limit(self):
        features = clean_features(amount=20000)
        features.payer.daily_limit = 100000
        features.payer.current_period.outflow.amount = 80000

        assert "limit_exceeded" not in codes(evaluate(features))

    def test_limit_stops_before_the_dict(self):
        features = clean_features(amount=2000000)
        fake_dict = FakeDict(features)

        result = evaluate(features, fake_dict)

        assert result.status == REJECTED
        assert fake_dict.calls == 0
        assert result.decision["stopped_before_dict"] is True

    def test_night_limit_between_people(self):
        features = at_night(clean_features(amount=150000))
        assert codes(evaluate(features))[0] == "limit_exceeded"

    def test_night_limit_does_not_apply_to_a_company_or_own_account(self):
        to_company = at_night(clean_features(amount=150000))
        to_company.destination.document_type = "PJ"

        own = at_night(clean_features(amount=150000))
        own.relationship.same_owner = True

        assert "limit_exceeded" not in codes(evaluate(to_company))
        assert "limit_exceeded" not in codes(evaluate(own))

    @pytest.mark.parametrize("side", ["payer", "destination"])
    def test_sanctioned_party_on_either_side(self, side):
        features = clean_features()
        getattr(features, side).restricted_list = "csnu"

        result = evaluate(features)

        assert result.status == REJECTED
        assert codes(result) == ["sanctioned_party"]
        assert result.decision["sanctions_freeze"] is True

    def test_betting_only_on_the_destination(self):
        to_bets = clean_features()
        to_bets.destination.restricted_list = "bets"
        from_bets = clean_features()
        from_bets.payer.restricted_list = "bets"

        assert codes(evaluate(to_bets)) == ["betting_destination"]
        assert evaluate(from_bets).status == APPROVED

    def test_court_order_alone_does_not_block(self):
        features = clean_features()
        features.destination.restricted_list = "court_order"

        assert evaluate(features).status == APPROVED

    def test_repeat_after_fraud_rejection(self):
        features = clean_features()
        features.relationship.fraud_rejections_24h = 1

        assert codes(evaluate(features)) == ["repeat_after_fraud_rejection"]

    def test_destination_account_blocked(self):
        from tests.unit.engine.features_factory import internal_destination

        features = clean_features()
        internal_destination(features, age_days=900).is_blocked = True

        assert codes(evaluate(features))[0] == "destination_account_blocked"

    @pytest.mark.parametrize(
        "amount,today,expected",
        [(20000, 0, False), (20001, 0, True), (10000, 90000, False), (10000, 90001, True)],
    )
    def test_new_device_limit(self, amount, today, expected):
        features = unregistered_device(clean_features(amount))
        features.payer.unregistered_amount_today = today

        result = evaluate(features)

        assert ("new_device_limit" in codes(result)) is expected
        if expected:
            assert result.status != APPROVED

    def test_registered_device_has_no_device_limit(self):
        features = clean_features(50000)
        features.payer.unregistered_amount_today = 500000

        assert "new_device_limit" not in codes(evaluate(features))

    def test_device_needs_three_days_and_seven_days_of_age(self):
        two_days = clean_features()
        two_days.device.approved_days = 2

        too_young = clean_features()
        too_young.device.first_approved_at = MOMENT - timedelta(days=6)

        expired = clean_features()
        expired.device.last_used_at = MOMENT - timedelta(days=366)

        for features in (two_days, too_young, expired):
            assert "new_device" in codes(evaluate(features))

    def test_cold_start_device_is_the_onboarding_one(self):
        features = clean_features(50000)
        features.payer.account_age_days = 5
        features.device.approved_devices_count = 0
        features.device.approved_days = 0

        result = evaluate(features)

        assert "new_device" not in codes(result)
        assert "new_device_limit" not in codes(result)

    def test_old_account_that_never_did_pix_has_an_unregistered_device(self):
        features = clean_features(50000)
        features.device.approved_devices_count = 0
        features.device.approved_days = 0

        assert "new_device_limit" in codes(evaluate(features))

    @pytest.mark.parametrize("amount,expected", [(17999, False), (18000, True), (20000, True)])
    def test_new_device_structuring(self, amount, expected):
        features = unregistered_device(clean_features(amount))
        features.payer.unregistered_near_limit_24h = 1

        assert ("new_device_structuring" in codes(evaluate(features))) is expected

    def test_dict_fraud_marker_needs_a_reinforcement(self):
        old = dict_answer(clean_features(), account=[marker("MULE_ACCOUNT", 30)])
        young = dict_answer(clean_features(), account=[marker("MULE_ACCOUNT", 30)])
        young.destination.account_age_days = 89
        fan_in = dict_answer(clean_features(), owner=[marker("SCAMMER_ACCOUNT", 30)])
        fan_in.destination.history.new_payers_7d = 2
        rejected_before = dict_answer(clean_features(), owner=[marker("SCAMMER_ACCOUNT", 30)])
        rejected_before.destination.history.fraud_rejected_payers_90d = 1

        assert codes(evaluate(old))[0] == "dict_marker"
        for features in (young, fan_in, rejected_before):
            assert codes(evaluate(features))[0] == "dict_fraud_marker"

    def test_old_marker_does_not_reject(self):
        features = dict_answer(clean_features(), account=[marker("MULE_ACCOUNT", 400)])
        features.destination.account_age_days = 30

        result = evaluate(features)

        assert codes(result)[0] == "dict_marker"
        assert result.status == TWO_FACTOR_REQUIRED

    def test_marker_older_than_five_years_is_ignored(self):
        features = dict_answer(clean_features(), account=[marker("MULE_ACCOUNT", 1900)])

        assert evaluate(features).status == APPROVED

    def test_other_marker_only_weighs_in_the_score(self):
        features = dict_answer(clean_features(), account=[marker("OTHER", 10)])

        result = evaluate(features)

        assert "dict_marker" not in codes(result)
        assert "dict_history" in codes(result)

    def test_messy_dict_answer_does_not_break_the_engine(self):
        for response in (None, {}, {"account": None}, {"account": {"fraud_markers": "x"}}, {"owner": {"fraud_markers": [1]}}):
            features = clean_features()
            features.destination.dict.response = response
            assert evaluate(features).status in (APPROVED, TWO_FACTOR_REQUIRED)

    def test_dict_unavailable_only_for_a_new_external_destination(self):
        from engine.features import DICT_UNAVAILABLE, DictFeatures

        unavailable = DictFeatures(status=DICT_UNAVAILABLE, response=None, fetched_at=None)

        known = clean_features()
        known.destination.dict = unavailable
        new = new_destination(clean_features())
        new.destination.dict = unavailable

        assert "dict_unavailable" not in codes(evaluate(known))
        assert codes(evaluate(new))[0] == "dict_unavailable"


class TestPolicy:
    """Uma linha por regra da seção 8."""

    def test_clear_risk(self):
        assert by_score(100, 0.5, 0.9) == (REJECTED, "risco_claro")

    def test_founded_suspicion(self):
        assert by_score(100, 0.10, 0.49) == (REJECTED, "fundada_suspeita")

    def test_identity_goes_to_2fa(self):
        assert by_score(100, 0.49, 0.5) == (TWO_FACTOR_REQUIRED, "identidade")

    def test_suspicion_when_2fa_is_worth_the_friction(self):
        # P × V × ρ = 0,05 × 100 × 0,7 = 3,5 > 3
        assert by_score(100, 0.05, 0.7) == (TWO_FACTOR_REQUIRED, "suspeita")
        # 0,05 × 100 × 0,5 = 2,5 < 3
        assert by_score(100, 0.05, 0.5) == (APPROVED, "risco_baixo")

    def test_floor_wins_ties_and_never_goes_down(self):
        assert decide(100, 0.0001, 0.3, floor=TWO_FACTOR_REQUIRED) == (TWO_FACTOR_REQUIRED, "regra_dura")
        assert decide(100, 0.0001, 0.3, floor=REJECTED) == (REJECTED, "regra_dura")
        assert decide(100, 0.6, 0.3, floor=TWO_FACTOR_REQUIRED) == (REJECTED, "risco_claro")

    def test_points_to_probability_table(self):
        """A tabela da seção 7."""
        for points, expected in ((0, 0.0001), (40, 0.0016), (80, 0.025), (100, 0.093), (120, 0.29), (140, 0.62)):
            assert probability(points) == pytest.approx(expected, rel=0.06)


class TestScore:
    def test_family_cap(self):
        evidences = [Evidence("new_device", params.IDENTITY, 25), Evidence("impossible_travel", params.IDENTITY, 25),
                     Evidence("shared_device", params.IDENTITY, 20)]

        assert score(evidences).points == 50

    def test_mitigation_floor(self):
        evidences = [Evidence("new_destination_account", params.DESTINATION, 30),
                     Evidence("recurring_destination", params.RELATIONSHIP, -20),
                     Evidence("own_account_established", params.RELATIONSHIP, -20),
                     Evidence("received_from_destination", params.RELATIONSHIP, -10)]

        assert score(evidences).points == 30 - 40

    def test_rho_is_weighted_by_points(self):
        evidences = [Evidence("new_device", params.IDENTITY, 30), Evidence("new_destination_account", params.DESTINATION, 30)]

        assert score(evidences).rho == pytest.approx((30 * 0.9 + 30 * 0.1) / 60)

    def test_pattern_carries_its_own_rho(self):
        evidences = [Evidence("takeover_cashout", params.PATTERN, 15, rho=0.9)]

        assert score(evidences).rho == pytest.approx(0.9)

    def test_amount_above_profile_is_continuous_and_capped(self):
        small = clean_features(80000)   # 2× o p90 combinado ~ 42.700
        huge = clean_features(10_000_000)
        huge.payer.daily_limit = huge.payer.balance = 20_000_000

        def points(features):
            return [ev for ev in evaluate(features).decision["signals"] if ev["code"] == "amount_above_profile"][0]["points"]

        assert 5 <= points(small) <= 8
        assert points(huge) == 30


class TestProperties:
    def test_no_layer_lowers_a_2fa_floor(self):
        """Propriedade: um piso de 2FA de regra dura nunca vira approved, com qualquer mitigante."""
        rng = random.Random(7)
        for _ in range(200):
            features = unregistered_device(clean_features(rng.randint(20001, 400000)))
            features.payer.balance = features.payer.daily_limit = 10_000_000
            features.relationship.same_owner = rng.random() < 0.5
            features.destination.account_age_days = rng.choice([1, 100, 2000])

            assert evaluate(features).status != APPROVED

    def test_pld_sensitive_codes_never_go_public(self):
        stored = [Reason(code, "x", 10) for code in PLD_SENSITIVE] + [Reason("first_payment_to_destination", "y", 15)]

        public = public_reasons(stored)

        assert not {reason.code for reason in public} & set(PLD_SENSITIVE)
        assert "risk_policy" in {reason.code for reason in public}

    def test_public_reasons_show_hard_rules_and_top_signals_only(self):
        stored = [Reason("dict_marker", "m"), Reason("a", "a", 5), Reason("b", "b", 30), Reason("c", "c", 20),
                  Reason("d", "d", 10), Reason("recurring_destination", "r", -20)]

        assert [reason.code for reason in public_reasons(stored)] == ["dict_marker", "b", "c", "d"]

    def test_payer_mule_alert_is_public_only_as_risk_policy(self):
        features = payer_profile(clean_features(380000), balance=400000, age_days=20)
        inflow_24h(features, 400000, new_counterparties=5)
        new_destination(features, age_days=50)

        result = evaluate(settle(features))
        public = [reason.code for reason in public_reasons(result.reasons)]

        assert "payer_pass_through" in codes(result)
        assert "payer_pass_through" not in public
        assert "risk_policy" in public

    def test_same_features_same_decision(self):
        """O motor é puro: o mesmo Features (inclusive de volta do JSON) dá a mesma decisão."""
        features = settle(new_destination(clean_features(300000), age_days=10))
        first = evaluate(features)

        replay = Features.from_dict(features.to_dict())
        second = evaluate(replay, lambda: replay.destination.dict)

        assert (first.status, first.score) == (second.status, second.score)

    def test_severity_order(self):
        assert SEVERITY[APPROVED] < SEVERITY[TWO_FACTOR_REQUIRED] < SEVERITY[REJECTED]
