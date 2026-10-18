"""Busca dos pesos e da política de custo que minimizam o custo real nos cenários.

    python calibration/calibrate.py               # busca completa + relatório
    python calibration/calibrate.py --baseline    # só avalia o motor como está

Como funciona:
  1. cada cenário (calibration/data/*.json, menos os vetados em review.json)
     vira um `Features` e passa UMA vez pelo motor de verdade até os sinais:
     regras duras (o piso) e as evidências ficam guardadas;
  2. uma configuração = pesos por família (multiplicador dos pontos), tetos,
     ρ, prior, cortes, c₂ e a política (cortes ou custo esperado puro);
  3. para cada configuração, os pontos são re-somados com `scoring.score` e
     decididos com `policy.decide` do próprio motor (params trocados em
     memória), e o custo vem de calibration/cost.py;
  4. busca aleatória + refinamento local no TREINO; o resultado que vale é o
     da VALIDAÇÃO (cenários que a busca não viu).

O que a busca NÃO mexe: as regras duras (obrigações legais e decisões já
tomadas) e os limiares internos de cada sinal.
"""

import argparse
import contextlib
import json
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "src"))
sys.path.insert(0, str(ROOT))

from engine import hard_rules, params, policy, signals  # noqa: E402
from engine.evidence import Evidence  # noqa: E402
from engine.measures import measure  # noqa: E402
from engine.result import APPROVED, REJECTED, TWO_FACTOR_REQUIRED, most_severe  # noqa: E402
from engine.scoring import score  # noqa: E402

import cost  # noqa: E402
from scenario import to_features  # noqa: E402

FAMILIES = list(params.FAMILIES)
MITIGATION = "mitigation"


# ── Cenários ─────────────────────────────────────────────────────


def load_scenarios(skip_difficulty: tuple = ()) -> List[dict]:
    review_path = ROOT / "data" / "review.json"
    vetoed = set()
    if review_path.exists():
        vetoed = {item["id"] for item in json.loads(review_path.read_text(encoding="utf-8")) if item.get("drop")}

    scenarios = []
    for path in sorted((ROOT / "data").glob("gen_*.json")):
        for item in json.loads(path.read_text(encoding="utf-8")):
            if item["id"] not in vetoed and item.get("difficulty") not in skip_difficulty:
                item["_source"] = path.stem
                scenarios.append(item)
    return scenarios


@dataclass
class Prepared:
    scenario: dict
    amount_reais: float
    floor: str                  # o piso das regras duras
    stopped: bool               # regra dura rejeitou antes do DICT: o score nem roda
    evidences: List[Evidence]


def prepare(scenario: dict, features=None) -> Prepared:
    """O motor de verdade até os sinais (mesma ordem do ScorecardEngine)."""
    f = features if features is not None else to_features(scenario)
    answer = f.destination.dict
    f.destination.dict = None

    m = measure(f)
    outcomes = hard_rules.run(hard_rules.PRE_DICT_RULES, f, m)
    if any(status == REJECTED for status, _ in outcomes):
        return Prepared(scenario, m.amount_reais, REJECTED, True, [])

    f.destination.dict = answer
    m = measure(f)
    outcomes = outcomes + hard_rules.run(hard_rules.DICT_RULES, f, m)
    floor = most_severe([status for status, _ in outcomes])
    return Prepared(scenario, m.amount_reais, floor, False, signals.collect(f, m))


# ── Configuração ─────────────────────────────────────────────────


def baseline_config() -> dict:
    return {
        "policy": "thresholds",
        "prior_odds": params.PRIOR_ODDS,
        "c_2fa": params.C_2FA,
        "c_reject": params.C_REJECT,
        "alpha": params.ALPHA,
        "p_fundada": params.P_FUNDADA_SUSPEITA,
        "p_claro": params.P_RISCO_CLARO,
        "rho_identity": params.RHO_IDENTITY,
        "mitigation_floor": params.MITIGATION_FLOOR,
        "scale": {family: 1.0 for family in FAMILIES + [MITIGATION]},
        "cap": {family: params.FAMILIES[family][0] for family in FAMILIES},
        "rho": {family: params.FAMILIES[family][1] for family in FAMILIES if params.FAMILIES[family][1] is not None},
    }


RHO_RANGES = {
    "identity": (0.6, 0.95),
    "magnitude": (0.2, 0.6),
    "velocity": (0.2, 0.6),
    "relationship": (0.1, 0.5),
    "destination": (0.05, 0.3),
    "payer_mule": (0.05, 0.3),
    "context": (0.1, 0.5),
}


def _log_uniform(rng, low, high):
    return math.exp(rng.uniform(math.log(low), math.log(high)))


def random_config(rng: random.Random) -> dict:
    base = baseline_config()
    p_fundada = _log_uniform(rng, 0.02, 0.4)
    return {
        "policy": rng.choice(["thresholds", "expected_cost"]),
        "prior_odds": _log_uniform(rng, 1 / 40_000, 1 / 2_500),
        "c_2fa": _log_uniform(rng, 1.0, 12.0),
        "c_reject": _log_uniform(rng, 5.0, 80.0),
        "alpha": rng.uniform(0.0, 0.3),
        "p_fundada": p_fundada,
        "p_claro": rng.uniform(max(p_fundada, 0.3), 0.9),
        "rho_identity": rng.uniform(0.3, 0.8),
        "mitigation_floor": rng.choice([-20, -30, -40, -50, -60]),
        "scale": {family: _log_uniform(rng, 0.5, 2.0) for family in FAMILIES + [MITIGATION]},
        "cap": {family: round(cap * _log_uniform(rng, 0.6, 1.6)) for family, cap in base["cap"].items()},
        "rho": {family: rng.uniform(*RHO_RANGES[family]) for family in base["rho"]},
    }


def neighbour(config: dict, rng: random.Random, step: float = 0.15) -> dict:
    """Uma configuração vizinha: mexe em 1 a 3 números."""
    new = json.loads(json.dumps(config))
    for _ in range(rng.randint(1, 3)):
        kind = rng.choice(["scale", "scale", "cap", "rho", "prior_odds", "c_2fa", "p_fundada", "p_claro",
                           "rho_identity", "mitigation_floor", "c_reject", "alpha", "policy"])
        jitter = math.exp(rng.gauss(0, step))
        if kind in ("scale", "cap", "rho"):
            key = rng.choice(list(new[kind]))
            value = new[kind][key] * jitter
            if kind == "cap":
                value = max(5, round(value))
            if kind == "rho":
                value = min(0.99, max(0.01, value))
            new[kind][key] = value
        elif kind == "policy":
            new["policy"] = "expected_cost" if new["policy"] == "thresholds" else "thresholds"
        elif kind == "mitigation_floor":
            new[kind] = max(-80, min(-10, new[kind] + rng.choice([-10, 10])))
        elif kind in ("p_fundada", "p_claro"):
            new[kind] = min(0.95, new[kind] * jitter)
            new["p_claro"] = max(new["p_claro"], new["p_fundada"])
        elif kind == "rho_identity":
            new[kind] = min(0.95, max(0.05, new[kind] * jitter))
        else:
            new[kind] = new[kind] * jitter
    return new


def _by_expected_cost(amount_reais: float, p: float, rho: float):
    """Política de custo puro: a ação de menor custo esperado, sem cortes fixos."""
    approve = p * amount_reais
    two_factor = p * amount_reais * (1 - rho) + (1 - p) * params.C_2FA
    reject = (1 - p) * (params.C_REJECT + params.ALPHA * amount_reais)
    best = min(approve, two_factor, reject)
    if best == reject and reject < two_factor:
        return REJECTED, "custo_esperado"
    if best == two_factor and two_factor < approve:
        return TWO_FACTOR_REQUIRED, "custo_esperado"
    return APPROVED, "custo_esperado"


@contextlib.contextmanager
def applied(config: dict):
    """Troca os números do motor em memória e devolve no fim."""
    names = ("PRIOR_ODDS", "C_2FA", "C_REJECT", "ALPHA", "P_FUNDADA_SUSPEITA", "P_RISCO_CLARO",
             "RHO_IDENTITY", "MITIGATION_FLOOR", "FAMILIES")
    saved = {name: getattr(params, name) for name in names}
    saved_by_score = policy.by_score
    try:
        params.PRIOR_ODDS = config["prior_odds"]
        params.C_2FA = config["c_2fa"]
        params.C_REJECT = config["c_reject"]
        params.ALPHA = config["alpha"]
        params.P_FUNDADA_SUSPEITA = config["p_fundada"]
        params.P_RISCO_CLARO = config["p_claro"]
        params.RHO_IDENTITY = config["rho_identity"]
        params.MITIGATION_FLOOR = config["mitigation_floor"]
        params.FAMILIES = {
            family: (config["cap"][family], config["rho"].get(family)) for family in saved["FAMILIES"]
        }
        if config["policy"] == "expected_cost":
            policy.by_score = _by_expected_cost
        yield
    finally:
        for name, value in saved.items():
            setattr(params, name, value)
        policy.by_score = saved_by_score


def decide(prepared: Prepared, config: dict) -> str:
    """Decisão com a configuração já aplicada (dentro de `applied`)."""
    if prepared.stopped:
        return REJECTED

    scale = config["scale"]
    evidences = [
        Evidence(ev.code, ev.family, int(round(ev.points * scale[MITIGATION if ev.points < 0 else ev.family])), ev.rho)
        for ev in prepared.evidences
    ]
    points = score(evidences)
    status, _ = policy.decide(prepared.amount_reais, points.probability, points.rho, prepared.floor)
    return status


# ── Avaliação ────────────────────────────────────────────────────


def decisions(prepared: List[Prepared], config: dict) -> List[str]:
    with applied(config):
        return [decide(p, config) for p in prepared]


def total_cost(prepared: List[Prepared], statuses: List[str], legit_weight: float) -> float:
    return sum(cost.cost(p.scenario, status, legit_weight) for p, status in zip(prepared, statuses))


def objective(prepared: List[Prepared], statuses: List[str], reference: Dict[float, float]) -> float:
    """Média, entre os pesos de legítimo, do custo relativo ao motor atual (1.0 = igual)."""
    return sum(total_cost(prepared, statuses, w) / reference[w] for w in cost.LEGIT_WEIGHTS) / len(cost.LEGIT_WEIGHTS)


def summary(prepared: List[Prepared], statuses: List[str]) -> dict:
    out = {"n": len(prepared)}
    for label in ("fraud", "legit"):
        rows = [(p, s) for p, s in zip(prepared, statuses) if p.scenario["label"] == label]
        out[label] = {status: sum(1 for _, s in rows if s == status) for status in (APPROVED, TWO_FACTOR_REQUIRED, REJECTED)}
        out[label]["n"] = len(rows)
    frauds = [(p, s) for p, s in zip(prepared, statuses) if p.scenario["label"] == "fraud"]
    total_fraud = sum(cost.amount(p.scenario) for p, _ in frauds) or 1
    out["fraud_value_lost_pct"] = round(100 * sum(cost.fraud_cost(p.scenario, s) for p, s in frauds) / total_fraud, 1)
    for w in cost.LEGIT_WEIGHTS:
        out[f"cost_w{w}"] = round(total_cost(prepared, statuses, w), 2)
    return out


def split(prepared: List[Prepared], seed: int, val_share: float = 0.3):
    """Treino e validação estratificados por arquivo de origem."""
    rng = random.Random(seed)
    train, val = [], []
    by_source: Dict[str, List[Prepared]] = {}
    for p in prepared:
        by_source.setdefault(p.scenario["_source"], []).append(p)
    for items in by_source.values():
        items = items[:]
        rng.shuffle(items)
        cut = round(len(items) * val_share)
        val += items[:cut]
        train += items[cut:]
    return train, val


PENALTY = 0.01     # por unidade de distância do motor atual: na dúvida, mexe pouco


def distance(config: dict) -> float:
    """Quanto a configuração se afasta do motor atual (soma de |log da razão| dos números)."""
    base = baseline_config()
    total = 0.0
    for key in ("prior_odds", "c_2fa", "c_reject", "p_fundada", "p_claro", "rho_identity"):
        total += abs(math.log(config[key] / base[key]))
    total += abs(config["alpha"] - base["alpha"]) * 10
    total += abs(config["mitigation_floor"] - base["mitigation_floor"]) / 20
    for group in ("scale", "cap", "rho"):
        for key, value in config[group].items():
            total += abs(math.log(value / base[group][key]))
    total += 1.0 if config["policy"] != base["policy"] else 0.0
    return total


def search(train: List[Prepared], n_random: int, n_local: int, seed: int) -> dict:
    rng = random.Random(seed)
    base = baseline_config()
    base_statuses = decisions(train, base)
    reference = {w: max(total_cost(train, base_statuses, w), 1e-9) for w in cost.LEGIT_WEIGHTS}

    def evaluate(config):
        return objective(train, decisions(train, config), reference) + PENALTY * distance(config)

    best, best_value = base, evaluate(base)
    for _ in range(n_random):
        candidate = random_config(rng)
        value = evaluate(candidate)
        if value < best_value:
            best, best_value = candidate, value

    for i in range(n_local):
        step = 0.3 if i < n_local // 2 else 0.1
        candidate = neighbour(best, rng, step)
        value = evaluate(candidate)
        if value <= best_value:
            best, best_value = candidate, value

    return best


def folds(prepared: List[Prepared], k: int, seed: int) -> List[List[Prepared]]:
    """k partes estratificadas por arquivo de origem."""
    rng = random.Random(seed)
    parts: List[List[Prepared]] = [[] for _ in range(k)]
    by_source: Dict[str, List[Prepared]] = {}
    for p in prepared:
        by_source.setdefault(p.scenario["_source"], []).append(p)
    offset = 0
    for items in by_source.values():
        items = items[:]
        rng.shuffle(items)
        for i, item in enumerate(items):
            parts[(i + offset) % k].append(item)
        offset += len(items)
    return parts


def cross_validate(prepared: List[Prepared], k: int, n_random: int, n_local: int, seed: int) -> dict:
    """A estimativa honesta do procedimento: busca em k−1 partes, mede na parte que ficou de fora."""
    parts = folds(prepared, k, seed)
    held_statuses_best, held_statuses_base, held = [], [], []
    per_fold = []
    for i, part in enumerate(parts):
        train = [p for j, other in enumerate(parts) if j != i for p in other]
        best = search(train, n_random, n_local, seed + i)
        base_s, best_s = decisions(part, baseline_config()), decisions(part, best)
        reference = {w: max(total_cost(part, base_s, w), 1e-9) for w in cost.LEGIT_WEIGHTS}
        per_fold.append(round(objective(part, best_s, reference), 4))
        held += part
        held_statuses_base += base_s
        held_statuses_best += best_s
    reference = {w: max(total_cost(held, held_statuses_base, w), 1e-9) for w in cost.LEGIT_WEIGHTS}
    return {
        "relative_cost_per_fold": per_fold,
        "relative_cost_pooled": round(objective(held, held_statuses_best, reference), 4),
        "baseline": summary(held, held_statuses_base),
        "tuned_out_of_sample": summary(held, held_statuses_best),
    }


def report(prepared, train, val, best, path: Path) -> dict:
    base = baseline_config()
    result = {"cost_model": {
        "friction_2fa": cost.FRICTION_2FA, "reject_fixed": cost.REJECT_FIXED, "reject_share": cost.REJECT_SHARE,
        "stop_intruder": cost.STOP_INTRUDER, "stop_deceived": cost.STOP_DECEIVED, "stop_mule": cost.STOP_MULE,
        "legit_weights": cost.LEGIT_WEIGHTS,
    }, "best_config": best}

    for name, subset in (("train", train), ("val", val), ("all", prepared)):
        base_statuses = decisions(subset, base)
        best_statuses = decisions(subset, best)
        reference = {w: max(total_cost(subset, base_statuses, w), 1e-9) for w in cost.LEGIT_WEIGHTS}
        result[name] = {
            "baseline": summary(subset, base_statuses),
            "best": summary(subset, best_statuses),
            "relative_cost": round(objective(subset, best_statuses, reference), 4),
        }

    changed = []
    base_statuses = decisions(prepared, base)
    best_statuses = decisions(prepared, best)
    for p, before, after in zip(prepared, base_statuses, best_statuses):
        if before != after:
            changed.append({"id": p.scenario["id"], "label": p.scenario["label"], "before": before, "after": after,
                            "amount": cost.amount(p.scenario), "narrative": p.scenario.get("narrative")})
    result["changed"] = changed
    result["anchors"] = anchors(best)

    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def anchors(config: dict) -> List[dict]:
    """Os cenários L e G do 4.2 (tests/unit/engine/test_scenarios.py): o que muda de decisão."""
    sys.path.insert(0, str(ROOT.parent))
    from tests.unit.engine.test_scenarios import SCENARIOS

    prepared = [prepare({"id": name}, build()) for name, build, _ in SCENARIOS]
    statuses = decisions(prepared, config)
    return [
        {"id": name, "expected": expected, "got": status}
        for (name, _, expected), status in zip(SCENARIOS, statuses)
        if status != expected
    ]


def main(argv: Optional[List[str]] = None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--random", type=int, default=3000)
    parser.add_argument("--local", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--skip-difficulty", nargs="*", default=[], help="ex.: hard")
    parser.add_argument("--out", default=str(ROOT / "results" / "best.json"))
    args = parser.parse_args(argv)

    prepared = [prepare(s) for s in load_scenarios(tuple(args.skip_difficulty))]
    train, val = split(prepared, args.seed)

    if args.baseline:
        print(json.dumps(summary(prepared, decisions(prepared, baseline_config())), indent=2))
        return

    cv = cross_validate(prepared, args.folds, args.random, args.local, args.seed)
    best = search(prepared, args.random, args.local, args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    result = report(prepared, train, val, best, out)
    result["cross_validation"] = cv
    result["distance_from_current"] = round(distance(best), 3)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("validação cruzada (fora da amostra):", cv["relative_cost_per_fold"], "→", cv["relative_cost_pooled"])
    print("  antes:", cv["baseline"])
    print("  depois:", cv["tuned_out_of_sample"])
    for name in ("train", "val", "all"):
        print(name, "custo relativo:", result[name]["relative_cost"])
        print("  antes:", result[name]["baseline"])
        print("  depois:", result[name]["best"])


if __name__ == "__main__":
    main()
