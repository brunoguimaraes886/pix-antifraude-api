"""Os testes unitários importam o código de src/ direto, sem API no meio.

É a exceção ao combinado dos testes de integração (que só falam HTTP), e
vale só para o que é puro: o motor (src/engine/) e as contas de período
(src/utils/periods.py). Nada aqui abre banco ou rede.
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
