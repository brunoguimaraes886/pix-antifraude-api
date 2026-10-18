"""O placar por família de golpe e por tipo de legítimo.

    python calibration/report.py               # bancada em memória
    python calibration/report.py --api         # o último replay pela API (results/api_replay.json)

"Barrado" = rejeitado. O 2FA conta à parte: ele para o invasor (que não tem
a biometria do dono), quase nunca o dono enganado ou o próprio laranja. Por
isso o "valor perdido" usa a chance de o 2FA parar cada golpe (cost.py).
"""

import argparse
import json
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "src"))
sys.path.insert(0, str(ROOT))

import cost  # noqa: E402

APPROVED, TWO_FACTOR, REJECTED = "approved", "two_factor_required", "rejected"

# Famílias de golpe, pelo que o banco pode fazer contra cada uma.
FAMILIES = OrderedDict(
    [
        ("Invasão de conta", "outra pessoa opera a conta: celular roubado, credencial vazada, SIM swap, malware, "
                             "acesso remoto"),
        ("Falsa central e impostores", "o dono é enganado por quem finge ser o banco, um parente, um suporte: "
                                       "falsa central, conta segura, motoboy, falso parente, Pix errado"),
        ("Compra e cobrança falsas", "o dono paga por algo que não existe: loja, vendedor, leilão, "
                                     "intermediário, fornecedor, boleto, emprego"),
        ("Investimento, amor e tarefas", "golpes longos, com valores que crescem"),
        ("Coação", "sequestro relâmpago, falso sequestro, extorsão"),
        ("Laranja pagando", "o próprio cliente repassa dinheiro de golpe: conta alugada, aberta para isso, "
                            "dormente reativada"),
        ("Pagamento a laranja ou aposta", "o destino é a peça conhecida: conta laranja, apostas ilegais"),
    ]
)

BY_TYPE = {
    "falsa_central": "Falsa central e impostores",
    "conta_segura": "Falsa central e impostores",
    "golpe_motoboy": "Falsa central e impostores",
    "falso_parente": "Falsa central e impostores",
    "falso_suporte": "Falsa central e impostores",
    "falso_advogado": "Falsa central e impostores",
    "pix_errado": "Falsa central e impostores",
    "falsa_loja": "Compra e cobrança falsas",
    "falso_vendedor": "Compra e cobrança falsas",
    "falso_leilao": "Compra e cobrança falsas",
    "falso_intermediario": "Compra e cobrança falsas",
    "falso_fornecedor": "Compra e cobrança falsas",
    "falsa_cobranca": "Compra e cobrança falsas",
    "falso_emprego": "Compra e cobrança falsas",
    "golpe_amor": "Investimento, amor e tarefas",
    "falso_investimento": "Investimento, amor e tarefas",
    "golpe_tarefas": "Investimento, amor e tarefas",
    "sequestro_relampago": "Coação",
    "falso_sequestro": "Coação",
    "extorsao": "Coação",
    "laranja_repasse": "Laranja pagando",
    "conta_alugada": "Laranja pagando",
    "conta_recem_aberta": "Laranja pagando",
    "conta_dormente": "Laranja pagando",
    "destino_marcado_dict": "Laranja pagando",
    "laranja_destino": "Pagamento a laranja ou aposta",
    "apostas_ilegais": "Pagamento a laranja ou aposta",
}

LEGIT = OrderedDict(
    [
        ("gen_legit_common", "Legítimos do dia a dia"),
        ("gen_legit_hard", "Legítimos que parecem golpe"),
    ]
)


def family(row: dict) -> str:
    """Invasão vem do operador (outra pessoa apertou o botão), o resto do tipo de golpe."""
    if row.get("operator") == "intruder":
        return "Invasão de conta"
    return BY_TYPE[row["fraud_type"]]


def _count(rows: List[dict], key: str) -> Dict[str, int]:
    return {status: sum(1 for r in rows if r[key] == status) for status in (APPROVED, TWO_FACTOR, REJECTED)}


def _lost(rows: List[dict], key: str) -> float:
    """Fração do valor dos golpes que se perde (2FA desconta a chance de parar cada um)."""
    total = sum(r["amount"] for r in rows) or 1
    lost = sum(cost.fraud_cost({**r, "pix": {"amount": r["amount"]}}, r[key]) for r in rows)
    return round(100 * lost / total, 1)


def by_family(rows: List[dict], key: str) -> List[dict]:
    frauds = [r for r in rows if r["label"] == "fraud"]
    out = []
    for name in FAMILIES:
        group = [r for r in frauds if family(r) == name]
        if group:
            out.append({"family": name, "n": len(group), **_count(group, key), "value_lost_pct": _lost(group, key)})
    return out


def by_legit(rows: List[dict], key: str) -> List[dict]:
    out = []
    for source, name in LEGIT.items():
        group = [r for r in rows if r["label"] == "legit" and r["source"] == source]
        out.append({"group": name, "n": len(group), **_count(group, key)})
    return out


def scoreboard(rows: List[dict], key: str) -> dict:
    frauds = [r for r in rows if r["label"] == "fraud"]
    legits = [r for r in rows if r["label"] == "legit"]
    return {
        "fraud": {**_count(frauds, key), "n": len(frauds), "value_lost_pct": _lost(frauds, key)},
        "legit": {**_count(legits, key), "n": len(legits)},
        "families": by_family(rows, key),
        "legit_groups": by_legit(rows, key),
    }


def memory_rows() -> List[dict]:
    """A bancada em memória: o motor de verdade sobre o `Features` montado do cenário."""
    from calibrate import load_scenarios
    from engine.scorecard_engine import ScorecardEngine
    from scenario import to_features

    rows = []
    for scenario in load_scenarios():
        features = to_features(scenario)
        answer = features.destination.dict
        features.destination.dict = None
        status = ScorecardEngine().evaluate(features, lambda: answer).status
        rows.append(
            {
                "id": scenario["id"],
                "label": scenario["label"],
                "fraud_type": scenario.get("fraud_type"),
                "operator": scenario.get("operator"),
                "source": scenario["_source"],
                "amount": float((scenario.get("pix") or {}).get("amount", 150.0)),
                "status_memory": status,
            }
        )
    return rows


def print_tables(board: dict) -> None:
    print("| Família | Golpes | Aprovados | 2FA | Rejeitados | Valor perdido |")
    print("|---|---|---|---|---|---|")
    for f in board["families"]:
        print(f"| {f['family']} | {f['n']} | {f[APPROVED]} | {f[TWO_FACTOR]} | {f[REJECTED]} | {f['value_lost_pct']}% |")
    t = board["fraud"]
    print(f"| **Total** | {t['n']} | {t[APPROVED]} | {t[TWO_FACTOR]} | {t[REJECTED]} | {t['value_lost_pct']}% |")
    print()
    print("| Legítimos | n | Aprovados | 2FA | Rejeitados |")
    print("|---|---|---|---|---|")
    for g in board["legit_groups"]:
        print(f"| {g['group']} | {g['n']} | {g[APPROVED]} | {g[TWO_FACTOR]} | {g[REJECTED]} |")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", action="store_true")
    args = parser.parse_args(argv)

    if args.api:
        rows = json.loads((ROOT / "results" / "api_replay.json").read_text(encoding="utf-8"))["rows"]
        key = "status_api"
    else:
        rows = memory_rows()
        key = "status_memory"

    print_tables(scoreboard(rows, key))


if __name__ == "__main__":
    main()
