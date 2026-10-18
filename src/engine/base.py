from abc import ABCMeta, abstractmethod
from typing import Callable

from engine.features import DictFeatures, Features
from engine.result import EngineResult

# A consulta ao DICT, pronta para chamar: sem argumentos, devolve o
# DictFeatures (ok, fallback ou unavailable). Quem monta é a API.
DictConsult = Callable[[], DictFeatures]


class FraudEngine(metaclass=ABCMeta):
    """O lugar do motor de decisão.

    Um motor é qualquer classe com um `evaluate`: recebe as features de um
    Pix e devolve a decisão. Ele roda em duas fases:

      1. regras duras que não dependem do DICT (o limite, por exemplo).
         Se já rejeitam, o motor para aqui e o DICT nem é consultado;
      2. consulta o DICT — chamando `consult_dict()` — e grava a resposta
         em `features.destination.dict`; depois, as regras que dependem dele.

    O motor não abre banco nem faz HTTP por conta própria: a consulta ao
    DICT chega como função, e o motor só decide SE e QUANDO chamá-la. Por
    isso dá pra testá-lo com uma função falsa no lugar do DICT.

    Quem escolhe o motor em uso é o `get_engine`, em src/engine/__init__.py.
    """

    @abstractmethod
    def evaluate(self, features: Features, consult_dict: DictConsult) -> EngineResult:
        raise NotImplementedError
