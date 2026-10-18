"""Os 238 cenários desafiadores (calibration/: 240 escritos, 2 descartados na revisão) como teste de não-regressão.

Os cenários foram escritos por agentes que não conheciam o motor; muitos
golpes ali são indistinguíveis de um Pix legítimo, então o motor NÃO acerta
todos (veja calibration/README.md). O teste não exige acerto: exige que uma
mudança no motor não piore o placar de hoje. Se melhorar, suba o piso.
"""

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

from engine.result import APPROVED, REJECTED
from tests.unit.engine.engine_runner import evaluate

CALIBRATION = Path(__file__).resolve().parents[3] / "calibration"
sys.path.insert(0, str(CALIBRATION))

from calibrate import load_scenarios  # noqa: E402
from scenario import to_features  # noqa: E402

# O placar do motor atual (238 cenários, 2 vetados na revisão).
MIN_FRAUD_STOPPED = 63      # golpes com 2FA ou rejeitados (de 119)
MIN_FRAUD_REJECTED = 36
MAX_LEGIT_REJECTED = 3      # legítimos barrados (de 119)


@pytest.fixture(scope="module")
def scoreboard() -> Counter:
    board = Counter()
    for scenario in load_scenarios():
        status = evaluate(to_features(scenario)).status
        board[(scenario["label"], status)] += 1
    return board


def test_bench_has_all_scenarios(scoreboard):
    assert sum(scoreboard.values()) == len(load_scenarios()) == 238


def test_frauds_stopped_do_not_drop(scoreboard):
    assert sum(n for (label, status), n in scoreboard.items() if label == "fraud" and status != APPROVED) >= (
        MIN_FRAUD_STOPPED
    )
    assert scoreboard[("fraud", REJECTED)] >= MIN_FRAUD_REJECTED


def test_legit_rejections_do_not_grow(scoreboard):
    assert scoreboard[("legit", REJECTED)] <= MAX_LEGIT_REJECTED


def test_payer_dict_annotations_exist():
    """O DICT do pagador vem de outro arquivo, anotado às cegas depois dos cenários."""
    annotated = json.loads((CALIBRATION / "data" / "payer_dict.json").read_text(encoding="utf-8"))
    with_dict = [s for s in load_scenarios() if (s.get("payer") or {}).get("dict")]

    assert len(with_dict) == len(annotated)
