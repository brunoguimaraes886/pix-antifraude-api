from abc import ABCMeta, abstractmethod

from engine.features import Features
from engine.result import EngineResult


class FraudEngine(metaclass=ABCMeta):
    """O lugar do motor de decisão.

    Um motor é qualquer classe com um `evaluate`: recebe as features de um
    Pix e devolve a decisão. Ele é puro de propósito — não abre banco, não
    chama DICT, não lê relógio. Tudo de que precisa chega no `Features`, e
    por isso o mesmo Features sempre dá a mesma decisão.

    Quem escolhe o motor em uso é o `get_engine`, em src/engine/__init__.py.
    """

    @abstractmethod
    def evaluate(self, features: Features) -> EngineResult:
        raise NotImplementedError
