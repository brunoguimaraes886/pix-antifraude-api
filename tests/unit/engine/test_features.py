import json

from engine.features import Features
from tests.unit.engine.features_factory import clean_features


class TestFeaturesSerialization:
    def test_to_dict_is_plain_json(self):
        """O Features vai para uma coluna JSONB: tem que sair em tipos de JSON."""
        as_dict = clean_features().to_dict()

        assert json.loads(json.dumps(as_dict)) == as_dict
        assert as_dict["transaction"]["transaction_date"] == "2026-10-17T14:00:00-03:00"
        assert as_dict["payer"]["current_period"]["kind"] == "day"
        assert as_dict["payer"]["current_period"]["outflow"]["amount"] == 0

    def test_round_trip(self):
        """O que foi gravado volta a ser o mesmo Features — dá pra reproduzir a decisão."""
        features = clean_features()

        assert Features.from_dict(features.to_dict()) == features
