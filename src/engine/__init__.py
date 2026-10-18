from engine.base import FraudEngine
from engine.features import Features
from engine.result import EngineResult
from engine.scorecard_engine import ScorecardEngine


def get_engine() -> FraudEngine:
    """O motor em uso. Trocar de motor é trocar esta linha."""
    return ScorecardEngine()
