from engine.features import DICT_FALLBACK, DICT_UNAVAILABLE
from engine.result import APPROVED, REJECTED, TWO_FACTOR_REQUIRED
from engine.rules_engine import RulesEngine, count_fraud_markers
from tests.unit.engine.features_factory import clean_features

MULE_MARKER = {"type": "MULE_ACCOUNT", "created_at": "2026-09-30T10:00:00-03:00"}


def codes(result) -> list:
    return [reason.code for reason in result.reasons]


class FakeDict:
    """O DICT de mentira: devolve o que o factory deixou em destination.dict e conta as consultas."""

    def __init__(self, features) -> None:
        self.answer = features.destination.dict
        self.calls = 0
        features.destination.dict = None

    def __call__(self):
        self.calls = self.calls + 1
        return self.answer


def evaluate(features, fake_dict=None):
    if fake_dict is None:
        fake_dict = FakeDict(features)

    return RulesEngine().evaluate(features, fake_dict)


class TestRulesEngine:
    def test_clean_pix_is_approved_without_reasons(self):
        result = evaluate(clean_features())

        assert result.status == APPROVED
        assert result.reasons == []

    def test_limit_counts_what_already_left_in_the_period(self):
        """O limite é do período, não do Pix: o que já saiu soma."""
        features = clean_features(amount=30000)
        features.payer.current_period.limit = 100000
        features.payer.current_period.outflow.amount = 80000

        result = evaluate(features)

        assert result.status == REJECTED
        assert codes(result) == ["limit_exceeded"]

    def test_exactly_at_the_limit_passes(self):
        features = clean_features(amount=20000)
        features.payer.current_period.limit = 100000
        features.payer.current_period.outflow.amount = 80000

        assert evaluate(features).status == APPROVED

    def test_dict_marker_on_account_or_owner_rejects(self):
        for subject in ("account", "owner"):
            features = clean_features()
            features.destination.dict.response[subject]["fraud_markers"] = [MULE_MARKER]

            result = evaluate(features)

            assert result.status == REJECTED, subject
            assert codes(result) == ["dict_fraud_marker"]

    def test_marker_from_fallback_also_counts(self):
        features = clean_features()
        features.destination.dict.status = DICT_FALLBACK
        features.destination.dict.response["account"]["fraud_markers"] = [MULE_MARKER]

        assert evaluate(features).status == REJECTED

    def test_external_destination_without_dict_asks_two_factor(self):
        features = clean_features()
        features.destination.dict.status = DICT_UNAVAILABLE
        features.destination.dict.response = None

        result = evaluate(features)

        assert result.status == TWO_FACTOR_REQUIRED
        assert codes(result) == ["dict_unavailable"]

    def test_internal_destination_without_dict_is_not_doubt(self):
        """Conta nossa a gente conhece por dentro: DICT fora não vira 2FA."""
        features = clean_features()
        features.destination.is_internal = True
        features.destination.dict.status = DICT_UNAVAILABLE
        features.destination.dict.response = None

        assert evaluate(features).status == APPROVED

    def test_limit_rejects_before_consulting_the_dict(self):
        """Regra dura que já rejeita: o DICT nem é consultado."""
        features = clean_features(amount=200000)
        features.payer.current_period.limit = 100000
        fake_dict = FakeDict(features)

        result = evaluate(features, fake_dict)

        assert result.status == REJECTED
        assert codes(result) == ["limit_exceeded"]
        assert fake_dict.calls == 0
        assert features.destination.dict is None

    def test_passing_the_hard_rules_consults_the_dict_once(self):
        features = clean_features()
        fake_dict = FakeDict(features)

        evaluate(features, fake_dict)

        assert fake_dict.calls == 1
        assert features.destination.dict is fake_dict.answer


class TestCountFraudMarkers:
    def test_tolerates_unexpected_formats(self):
        assert count_fraud_markers(None) == 0
        assert count_fraud_markers({}) == 0
        assert count_fraud_markers({"account": None}) == 0
        assert count_fraud_markers({"account": {"fraud_markers": "x"}}) == 0
        assert count_fraud_markers({"account": {"fraud_markers": [MULE_MARKER]}, "owner": {"fraud_markers": [MULE_MARKER]}}) == 2
