from engine.features import DICT_FALLBACK, DICT_UNAVAILABLE
from engine.result import APPROVED, REJECTED, TWO_FACTOR_REQUIRED
from engine.rules_engine import RulesEngine, count_fraud_markers
from tests.unit.engine.features_factory import clean_features

MULE_MARKER = {"type": "MULE_ACCOUNT", "created_at": "2026-09-30T10:00:00-03:00"}


def codes(result) -> list:
    return [reason.code for reason in result.reasons]


class TestRulesEngine:
    def test_clean_pix_is_approved_without_reasons(self):
        result = RulesEngine().evaluate(clean_features())

        assert result.status == APPROVED
        assert result.reasons == []

    def test_limit_counts_what_already_left_in_the_period(self):
        """O limite é do período, não do Pix: o que já saiu soma."""
        features = clean_features(amount=30000)
        features.payer.current_period.limit = 100000
        features.payer.current_period.outflow.amount = 80000

        result = RulesEngine().evaluate(features)

        assert result.status == REJECTED
        assert codes(result) == ["limit_exceeded"]

    def test_exactly_at_the_limit_passes(self):
        features = clean_features(amount=20000)
        features.payer.current_period.limit = 100000
        features.payer.current_period.outflow.amount = 80000

        assert RulesEngine().evaluate(features).status == APPROVED

    def test_dict_marker_on_account_or_owner_rejects(self):
        for subject in ("account", "owner"):
            features = clean_features()
            features.destination.dict.response[subject]["fraud_markers"] = [MULE_MARKER]

            result = RulesEngine().evaluate(features)

            assert result.status == REJECTED, subject
            assert codes(result) == ["dict_fraud_marker"]

    def test_marker_from_fallback_also_counts(self):
        features = clean_features()
        features.destination.dict.status = DICT_FALLBACK
        features.destination.dict.response["account"]["fraud_markers"] = [MULE_MARKER]

        assert RulesEngine().evaluate(features).status == REJECTED

    def test_external_destination_without_dict_asks_two_factor(self):
        features = clean_features()
        features.destination.dict.status = DICT_UNAVAILABLE
        features.destination.dict.response = None

        result = RulesEngine().evaluate(features)

        assert result.status == TWO_FACTOR_REQUIRED
        assert codes(result) == ["dict_unavailable"]

    def test_internal_destination_without_dict_is_not_doubt(self):
        """Conta nossa a gente conhece por dentro: DICT fora não vira 2FA."""
        features = clean_features()
        features.destination.is_internal = True
        features.destination.dict.status = DICT_UNAVAILABLE
        features.destination.dict.response = None

        assert RulesEngine().evaluate(features).status == APPROVED

    def test_most_severe_wins_and_every_reason_is_kept(self):
        features = clean_features(amount=200000)
        features.payer.current_period.limit = 100000
        features.destination.dict.status = DICT_UNAVAILABLE
        features.destination.dict.response = None

        result = RulesEngine().evaluate(features)

        assert result.status == REJECTED
        assert codes(result) == ["limit_exceeded", "dict_unavailable"]


class TestCountFraudMarkers:
    def test_tolerates_unexpected_formats(self):
        assert count_fraud_markers(None) == 0
        assert count_fraud_markers({}) == 0
        assert count_fraud_markers({"account": None}) == 0
        assert count_fraud_markers({"account": {"fraud_markers": "x"}}) == 0
        assert count_fraud_markers({"account": {"fraud_markers": [MULE_MARKER]}, "owner": {"fraud_markers": [MULE_MARKER]}}) == 2
