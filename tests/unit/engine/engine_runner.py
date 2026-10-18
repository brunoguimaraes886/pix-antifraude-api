from engine.scorecard_engine import ScorecardEngine


class FakeDict:
    """O DICT de mentira: devolve o que o cenário deixou em destination.dict e conta as consultas."""

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

    return ScorecardEngine().evaluate(features, fake_dict)


def codes(result) -> list:
    return [reason.code for reason in result.reasons]
