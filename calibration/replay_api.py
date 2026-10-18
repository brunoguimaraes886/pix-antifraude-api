"""Os 238 cenários pela API de verdade: banco, mock do DICT e HTTP.

    docker compose up -d
    python calibration/replay_api.py

A bancada em memória (calibrate.py) entrega o `Features` pronto ao motor.
Aqui não: cada cenário vira o que a API leria no banco (cliente, conta,
extrato de 30 dias, Pix anteriores, aparelhos, outros clientes pagando o
mesmo destino, listas restritivas) e as respostas do DICT no MockServer. O
Pix do cenário entra pelo POST /pix/transaction, e a API monta o resto
sozinha: resumo diário, features, consulta ao DICT, motor, gravação.

Mede a latência (no cliente e a que a API grava) e compara a decisão com a
da bancada em memória. Diferença = o cenário pedia algo que o histórico não
consegue reproduzir do mesmo jeito (veja `notes` em results/api_replay.json).

Cada cenário usa contas novas, com número aleatório: rodar de novo não
esbarra no que já está no banco.
"""

import argparse
import json
import math
import statistics
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
for path in (str(REPO), str(REPO / "src"), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from sqlalchemy import text  # noqa: E402

from calibrate import load_scenarios  # noqa: E402
from engine.features import Features  # noqa: E402
from engine.scorecard_engine import ScorecardEngine  # noqa: E402
from scenario import DAY, KNOWN_RELATIONSHIP, cents, to_features  # noqa: E402
from tests.utils import DictMock, RandomGenerator, RequestGenerator  # noqa: E402
from tests.utils.scenario import OUR_ISPB, engine, iso  # noqa: E402
from utils.geo import EARTH_RADIUS_KM  # noqa: E402
from utils.periods import current_period, local_day_start  # noqa: E402

import report  # noqa: E402

HERE = {"latitude": -23.56, "longitude": -46.65}
IP = "198.51.100.23"
OTHER_IP = "203.0.113.9"
EXTERNAL = "60701190"
SUSPICION_REASON = "scam_drain_pattern"     # qualquer motivo que não é limite nem operacional
NEUTRAL_REASON = "limit_exceeded"           # rejeição que não é suspeita


# ── Banco ────────────────────────────────────────────────────────


class Db:
    """As inserções de um cenário, numa transação só."""

    def __init__(self, connection) -> None:
        self.c = connection
        self.status = {
            row[0]: row[1] for row in connection.execute(text("SELECT enumerator, id FROM analysis_status"))
        }

    def customer(self, document: str, birth_date) -> int:
        return self.c.execute(
            text(
                "INSERT INTO customer (customer_key, document_number, name, birth_date) "
                "VALUES (:key, :document, 'Cenário', :birth) RETURNING id"
            ),
            {"key": str(uuid4()), "document": document, "birth": birth_date},
        ).scalar()

    def account(self, customer_id: int, opening: datetime, balance: int, daily: int, nightly: int) -> dict:
        number = RandomGenerator.account_number()
        account_id = self.c.execute(
            text(
                "INSERT INTO account (account_key, customer_id, branch, account_number, opening_date, balance, "
                "daily_limit, nightly_limit) VALUES (:key, :customer, '0001', :number, :opening, :balance, "
                ":daily, :nightly) RETURNING id"
            ),
            {
                "key": str(uuid4()),
                "customer": customer_id,
                "number": number,
                "opening": opening,
                "balance": balance,
                "daily": daily,
                "nightly": nightly,
            },
        ).scalar()
        return {"account_id": account_id, "participant": OUR_ISPB, "branch": "0001", "account_number": number}

    def statements(self, rows: List[dict]) -> None:
        if rows:
            self.c.execute(
                text(
                    "INSERT INTO account_statement (account_id, direction, amount, counterparty_participant, "
                    "counterparty_branch, counterparty_account_number, counterparty_document, occurred_at) "
                    "VALUES (:account_id, :direction, :amount, :participant, :branch, :number, :document, :at)"
                ),
                rows,
            )

    def pix(
        self,
        when: datetime,
        destination: dict,
        status: str,
        source_id: Optional[int],
        amount: int = 1000,
        device: str = "dvc-x",
        channel: str = "app",
        ip: str = IP,
        reasons: tuple = (),
        location: Optional[dict] = None,
        destination_evidence: bool = False,
        destination_account_id: Optional[int] = None,
    ) -> None:
        pix_id = self.c.execute(
            text(
                "INSERT INTO pix_transaction (pix_id, amount, transaction_date, source_account_id, "
                "destination_participant, destination_branch, destination_account_number, destination_opening_date, "
                "destination_document_number, destination_account_id, device_id, channel, ip, latitude, longitude, "
                "payload) VALUES (:pix_id, :amount, :when, :source, :participant, :branch, :number, :opening, "
                ":document, :destination_id, :device, :channel, :ip, :lat, :lon, '{}'::jsonb) RETURNING id"
            ),
            {
                "pix_id": f"replay-hist-{uuid4()}",
                "amount": amount,
                "when": when,
                "source": source_id,
                "participant": destination["participant"],
                "branch": destination["branch"],
                "number": destination["account_number"],
                "opening": destination.get("opening", when - timedelta(days=900)),
                "document": destination["document_number"],
                "destination_id": destination_account_id,
                "device": device,
                "channel": channel,
                "ip": ip,
                "lat": location["latitude"] if location else None,
                "lon": location["longitude"] if location else None,
            },
        ).scalar()

        decision = json.dumps({"destination_evidence": destination_evidence})
        analysis_id = self.c.execute(
            text(
                "INSERT INTO transaction_analysis (analysis_key, pix_transaction_id, status_id, latency_ms, decision) "
                "VALUES (:key, :pix, :status, 0, CAST(:decision AS jsonb)) RETURNING id"
            ),
            {"key": str(uuid4()), "pix": pix_id, "status": self.status[status], "decision": decision},
        ).scalar()

        for code in reasons:
            self.c.execute(
                text("INSERT INTO analysis_reason (analysis_id, reason_code, message) VALUES (:a, :code, 'replay')"),
                {"a": analysis_id, "code": code},
            )

    def block(self, account_id: int, started: datetime, ended: Optional[datetime]) -> None:
        self.c.execute(
            text(
                "INSERT INTO account_block (account_id, reason, started_at, ended_at) "
                "VALUES (:a, 'replay', :s, :e)"
            ),
            {"a": account_id, "s": started, "e": ended},
        )

    def restricted(self, document: str, list_name: str) -> None:
        self.c.execute(
            text(
                "INSERT INTO restricted_party (document_number, list, reason, listed_at) "
                "VALUES (:d, :l, 'replay', CURRENT_DATE) ON CONFLICT DO NOTHING"
            ),
            {"d": document, "l": list_name},
        )


def external(document: Optional[str] = None, opening: Optional[datetime] = None) -> dict:
    account = {
        "participant": EXTERNAL,
        "branch": "0001",
        "account_number": RandomGenerator.account_number(),
        "document_number": document or RandomGenerator.cpf(),
    }
    if opening is not None:
        account["opening"] = opening
    return account


def stmt(account_id: int, direction: str, amount: int, counterparty: dict, at: datetime) -> dict:
    return {
        "account_id": account_id,
        "direction": direction,
        "amount": max(1, int(round(amount))),
        "participant": counterparty["participant"],
        "branch": counterparty["branch"],
        "number": counterparty["account_number"],
        "document": counterparty["document_number"],
        "at": at,
    }


def spread(start: datetime, end: datetime, n: int) -> List[datetime]:
    """n instantes espalhados em (start, end)."""
    step = (end - start) / (n + 1)
    return [start + step * (i + 1) for i in range(n)]


def document_for(kind: str) -> str:
    return RandomGenerator.cnpj() if kind == "PJ" else RandomGenerator.cpf()


# ── Conta nossa: perfil, habitual de 30 dias e as últimas 24h ─────


def out_amounts(n: int, average: int, p90: int, fixed: List[int]) -> List[int]:
    """n valores de saída (contando os `fixed`) com média ≈ average e p90 ≈ p90.

    O p90 do banco é percentile_cont(0.9): os valores do índice ⌊0,9·(n−1)⌋
    para cima ficam iguais ao p90; o resto acerta a média.
    """
    generic = max(0, n - len(fixed))
    if generic == 0:
        return []

    top = min(generic, n - math.floor(0.9 * (n - 1)))
    rest = generic - top
    if rest == 0:
        return [p90] * top

    low = (n * average - top * p90 - sum(fixed)) / rest
    low = max(100, min(p90, low))
    return [p90] * top + [int(low)] * rest


def build_account(
    db: Db,
    data: dict,
    moment: datetime,
    document: str,
    customer_id: Optional[int],
    flow: dict,
    fixed: List[tuple],
    notes: List[str],
) -> dict:
    """Uma conta nossa com o histórico que o cenário descreve.

    `flow`: as últimas 24h (entrada, saída, contrapartes novas).
    `fixed`: (sentido, valor, contraparte, quando) que já existem por causa da
    relação com o destino; as saídas entram na conta do habitual de 30 dias
    como qualquer saída.
    """
    age_years = int(data.get("age_years", 41))
    birth = moment.date().replace(year=moment.year - age_years) - timedelta(days=1)
    age_days = int(data.get("account_age_days", 600))
    opening = moment - timedelta(days=age_days, minutes=1)

    if customer_id is None:
        customer_id = db.customer(document, birth)

    account = db.account(
        customer_id,
        opening,
        cents(data.get("balance", 5000.0)),
        cents(data.get("daily_limit", 10000.0)),
        cents(data.get("nightly_limit", 1000.0)),
    )
    account.update(document_number=document, opening=opening, age_days=age_days)
    account_id = account["account_id"]

    day_start = local_day_start(moment)
    history_days = min(30, age_days)
    wanted_history = int(data.get("history_days", 30))
    if wanted_history != history_days and not (wanted_history == 30 and age_days >= 30):
        notes.append(f"history_days {wanted_history} vira {history_days} (a API conta pela abertura)")

    fixed_rows = [stmt(account_id, d, a, counterparty, at) for d, a, counterparty, at in fixed]
    regular_out = [external() for _ in range(5)]
    regular_in = [external() for _ in range(3)]
    rows = []

    # Habitual: saídas dos 30 dias antes do dia do Pix.
    per_day_out = float(data.get("pix_out_per_day", 0.8))
    typical = data.get("typical_large_pix", 400.0)
    average_out = data.get("avg_pix_out", 150.0)
    n_out = round(per_day_out * history_days) if history_days and typical is not None else 0
    in_window = [
        row for row in fixed_rows
        if row["direction"] == "out" and day_start - timedelta(days=30) <= row["at"] < day_start
    ]
    amounts = out_amounts(
        n_out, cents(average_out if average_out is not None else typical), cents(typical) if typical else 0,
        [row["amount"] for row in in_window],
    )
    n_night = night_count(data.get("night_share", 0.2) or 0, n_out)
    for i, amount in enumerate(amounts):
        rows.append(stmt(account_id, "out", amount, regular_out[i % 5], habitual_at(day_start, history_days, i, i < n_night)))

    # Habitual: entradas.
    per_day_in = float(data.get("pix_in_per_day", 0.2))
    n_in = round(per_day_in * history_days) if history_days else 0
    for i in range(n_in):
        at = habitual_at(day_start, history_days, i, False)
        rows.append(stmt(account_id, "in", cents(data.get("avg_pix_in", 2000.0)), regular_in[i % 3], at))

    # As contrapartes habituais já apareceram antes (45 dias: fora da janela de 30).
    old = day_start - timedelta(days=45)
    for counterparty in regular_out:
        rows.append(stmt(account_id, "out", 100, counterparty, old))
    for counterparty in regular_in:
        rows.append(stmt(account_id, "in", 100, counterparty, old))

    # Últimas 24h: dentro do período atual e do próprio dia, para não sujar o habitual.
    start = max(current_period(moment).start, day_start)
    rows += flow_rows(account_id, flow, start, moment, regular_in, regular_out, notes)

    db.statements(rows + fixed_rows)

    for i in range(int(data.get("past_account_blocks", 0))):
        started = moment - timedelta(days=400 + 30 * i)
        db.block(account_id, started, started + timedelta(days=2))

    return account


def night_count(share: float, n: int) -> int:
    """Quantas saídas à noite, sem o arredondamento cruzar o corte de 10% do `unusual_night`."""
    count = round(share * n)
    if n and share >= 0.10:
        count = max(count, math.ceil(0.10 * n))
    elif n:
        count = min(count, math.ceil(0.10 * n) - 1)
    return max(0, count)


def habitual_at(day_start: datetime, history_days: int, i: int, night: bool) -> datetime:
    """Quando cai o i-ésimo movimento do habitual: na janela de 30 dias, mas nunca ontem.

    Ontem pode estar dentro das últimas 24h e do período atual (a noite
    começa às 20h do dia anterior), e aí o habitual sujaria o fluxo recente.
    """
    if history_days >= 2:
        day = day_start - timedelta(days=2 + i % (history_days - 1))
        return day + timedelta(hours=22 if night else 12)
    return day_start - timedelta(days=1) + timedelta(minutes=5)


def flow_rows(account_id, flow, start, moment, regular_in, regular_out, notes) -> List[dict]:
    rows = []
    in_amount = cents(flow.get("inflow_amount", 0) or 0)
    in_count = int(flow.get("inflow_count", 0) or 0)
    in_new = int(flow.get("inflow_new_senders", 0) or 0)
    if in_amount and not in_count:
        in_count = 1
    in_new = min(in_new, in_count)
    match_amount = flow.get("_match_amount")
    match = bool(flow.get("_match"))

    amounts = split(in_amount, in_count)
    senders = [external() for _ in range(in_new)] + [regular_in[i % 3] for i in range(in_count - in_new)]

    if match and in_new and in_count:
        if in_count == 1:
            amounts = [in_amount]
        else:
            amounts = [match_amount] + split(max(in_count - 1, in_amount - match_amount), in_count - 1)
    elif match_amount and in_new:
        def matches(values):
            return any(abs(v - match_amount) <= 0.05 * match_amount for v in values[:in_new])

        if matches(amounts) and in_count >= 2:
            amounts = [int(v * (0.6 if i % 2 == 0 else 1.4)) for i, v in enumerate(amounts)]
            amounts[-1] += in_amount - sum(amounts)
        if matches(amounts):
            notes.append("entrada de desconhecido com o mesmo valor do Pix (matching_recent_inflow) inevitável")

    for when, amount, sender in zip(spread(start, moment, in_count), amounts, senders):
        rows.append(stmt(account_id, "in", amount, sender, when))

    out_amount = cents(flow.get("outflow_amount", 0) or 0)
    out_count = int(flow.get("outflow_count", 0) or 0)
    if out_amount and not out_count:
        out_count = 1
    out_new = min(int(flow.get("outflow_new_recipients", 0) or 0), out_count)
    recipients = [external() for _ in range(out_new)] + [regular_out[i % 5] for i in range(out_count - out_new)]
    for when, amount, recipient in zip(spread(start, moment, out_count), split(out_amount, out_count), recipients):
        rows.append(stmt(account_id, "out", amount, recipient, when))

    return rows


def split(total: int, n: int) -> List[int]:
    if n <= 0:
        return []
    base = total // n
    return [base] * (n - 1) + [total - base * (n - 1)]


# ── Um cenário inteiro ───────────────────────────────────────────


def realize(scenario: dict) -> dict:
    """Grava o mundo do cenário e devolve o payload do Pix (mais anotações)."""
    notes: List[str] = []
    pix = scenario.get("pix") or {}
    payer_data = scenario.get("payer") or {}
    flow = dict(scenario.get("flow_24h") or {})
    device = scenario.get("device") or {}
    velocity = scenario.get("velocity") or {}
    dest_data = scenario.get("destination") or {}
    relationship = scenario.get("relationship")
    if relationship is None:
        relationship = KNOWN_RELATIONSHIP

    hour = int(pix.get("hour", 14)) % 24
    moment = DAY.replace(hour=hour, minute=30)
    amount = cents(pix.get("amount", 150.0))
    flow["_match_amount"] = amount
    flow["_match"] = flow.get("matching_inflow_from_stranger", False)

    payer_type = payer_data.get("type", "PF")
    payer_document = document_for(payer_type)

    # O destino primeiro: a relação com ele vira extrato do pagador.
    internal = dest_data.get("bank", "other") == "same"
    dest_type = dest_data.get("type", "PF")
    same_owner = bool(dest_data.get("same_owner", False))
    dest_document = payer_document if same_owner else document_for(dest_type)
    dest_age = int(dest_data.get("account_age_days", 900))
    dest_opening = moment - timedelta(days=dest_age, minutes=1)

    with engine().begin() as connection:
        db = Db(connection)

        payer_customer = None
        destination_account = None
        if internal:
            data = dict(dest_data.get("internal") or {})
            data.setdefault("account_age_days", dest_age)
            data.setdefault("balance", 1000.0)
            data["type"] = dest_type
            dest_flow = {
                "inflow_amount": data.get("inflow_24h_amount", 0),
                "inflow_count": data.get("inflow_24h_count", 0),
                "inflow_new_senders": data.get("inflow_24h_new_senders", 0),
                "outflow_amount": data.get("outflow_24h_amount", 0),
                "outflow_count": 1 if data.get("outflow_24h_amount") else 0,
            }
            if same_owner:
                birth = moment.date().replace(year=moment.year - int(payer_data.get("age_years", 41)))
                payer_customer = db.customer(payer_document, birth - timedelta(days=1))
            destination_account = build_account(
                db, data, moment, dest_document, payer_customer, dest_flow, [], notes
            )
            destination = dict(destination_account)
            if data.get("blocked"):
                db.block(destination["account_id"], moment - timedelta(days=1), None)
            for i in range(int(data.get("past_rejected_pix_in", 0))):
                db.pix(
                    moment - timedelta(days=60 + i), destination, "rejected", None,
                    reasons=(SUSPICION_REASON,), destination_account_id=destination["account_id"],
                )
        else:
            destination = external(dest_document, dest_opening)
        destination["opening"] = dest_opening

        # Relação: o que o pagador já pagou a este destino e recebeu dele.
        payer_flow_out = []
        previous = int(relationship.get("previous_payments") or 0)
        if previous:
            total = cents(relationship.get("previous_total") or 0)
            largest = cents(relationship.get("largest_previous")) if relationship.get("largest_previous") else None
            if not total:
                total = (largest or 10000) * previous
            if largest is None:
                largest = total // previous
            others = split(max(previous - 1, total - largest), previous - 1) if previous > 1 else []
            first_days = relationship.get("first_payment_days_ago")
            last_days = relationship.get("last_payment_days_ago")
            if first_days is None:
                first_days = last_days if last_days is not None else 60
            if last_days is None:
                last_days = first_days
            for i, value in enumerate(others + [largest]):
                days = first_days + (last_days - first_days) * (i / (previous - 1) if previous > 1 else 1)
                at = min(moment - timedelta(days=float(days)), moment - timedelta(minutes=10))
                payer_flow_out.append(("out", value, destination, at))
                if at >= moment - timedelta(hours=24):
                    # Pago nas últimas 24h: já é parte da saída das 24h do cenário.
                    flow["outflow_amount"] = max(0, float(flow.get("outflow_amount", 0) or 0) - value / 100)
                    flow["outflow_count"] = max(0, int(flow.get("outflow_count", 0) or 0) - 1)
        received = cents(relationship.get("received_from_destination_total") or 0)
        if received:
            days = relationship.get("first_received_days_ago")
            payer_flow_out.append(
                ("in", received, destination, moment - timedelta(days=float(days if days is not None else 10)))
            )

        payer = build_account(db, payer_data, moment, payer_document, payer_customer, flow, payer_flow_out, notes)
        payer_id = payer["account_id"]
        if payer_data.get("restricted"):
            db.restricted(payer_document, payer_data["restricted"])
        if dest_data.get("restricted"):
            db.restricted(dest_document, dest_data["restricted"])

        # Pix rejeitados por suspeita no passado (contexto).
        hist_channel = "app" if device.get("channel_used_before", True) else "web"
        registered = bool(device.get("registered", True))
        hist_ip = IP if device.get("ip_seen_before", registered) else OTHER_IP
        anchor_device = f"dvc-{payer['account_number']}-h"
        for i in range(int(payer_data.get("past_rejected_pix", 0))):
            db.pix(moment - timedelta(days=60 + i), external(), "rejected", payer_id, device=anchor_device,
                   channel=hist_channel, ip=hist_ip, reasons=(SUSPICION_REASON,))
        # Uma tentativa antiga não aprovada: o canal e o IP já usados (ou não).
        db.pix(moment - timedelta(days=90), external(), "two_factor_required", payer_id, device=anchor_device,
               channel=hist_channel, ip=hist_ip, reasons=("new_device",))

        # ── Aparelho ──────────────────────────────────────────────
        current_device = f"dvc-{payer['account_number']}-{'main' if registered else 'new'}"
        if registered:
            for days in (200, 120, 60, 10, 3):
                db.pix(moment - timedelta(days=days), external(), "approved", payer_id, device=current_device,
                       channel=hist_channel, ip=hist_ip)
        others = int(device.get("other_registered_devices", 0 if registered else 1))
        for k in range(others):
            for days in (150, 100, 50):
                db.pix(moment - timedelta(days=days), external(), "approved", payer_id,
                       device=f"dvc-{payer['account_number']}-o{k}", channel=hist_channel, ip=hist_ip)
        for k in range(int(device.get("other_accounts_on_device_30d", 0))):
            other = db.account(db.customer(RandomGenerator.cpf(), "1990-01-01"), moment - timedelta(days=400),
                               100000, 1000000, 100000)
            db.pix(moment - timedelta(days=5 + k), external(), "approved", other["account_id"], device=current_device)

        # ── Tentativas nas últimas 24h ────────────────────────────
        attempts = []     # (quando, kwargs)
        to_destination = int(relationship.get("attempts_to_destination_24h") or 0)
        blocked = int(relationship.get("blocked_attempts_24h") or 0)
        fraud = int(relationship.get("fraud_rejections_24h") or 0)
        blocked = max(blocked, fraud)
        to_destination = max(to_destination, blocked)
        last_amount = cents(relationship.get("last_attempt_amount")) or amount
        for i in range(to_destination):
            if i < fraud:
                status, reasons = "rejected", (SUSPICION_REASON,)
            elif i < blocked:
                status, reasons = "two_factor_required", ("first_payment_to_destination",)
            else:
                status, reasons = "rejected", (NEUTRAL_REASON,)
            attempts.append((moment - timedelta(minutes=5 + 10 * (to_destination - 1 - i)), dict(
                destination=destination, status=status, reasons=reasons, amount=last_amount, device=current_device,
                destination_account_id=destination.get("account_id"),
            )))

        for j in range(int(device.get("near_200_from_unregistered_24h", 0))):
            attempts.append((moment - timedelta(hours=3, minutes=j), dict(
                destination=external(), status="two_factor_required", reasons=("new_device_limit",), amount=19000,
                device=f"dvc-{payer['account_number']}-u",
            )))

        sent_today = cents(device.get("unregistered_sent_today", 0) or 0)
        if sent_today:
            when = max(local_day_start(moment), moment - timedelta(hours=23)) + timedelta(minutes=1)
            attempts.append((when, dict(destination=external(), status="approved", reasons=(), amount=sent_today,
                                        device=f"dvc-{payer['account_number']}-t")))

        has_geo = bool(device.get("has_geolocation", True))
        distance = device.get("distance_from_last_km", 0.4 if has_geo else None)
        minutes = device.get("minutes_since_last_location", 600.0 if has_geo else None)
        if has_geo and distance is not None and minutes is not None:
            located = {
                "latitude": HERE["latitude"] + math.degrees(float(distance) / EARTH_RADIUS_KM),
                "longitude": HERE["longitude"],
            }
            entry = dict(destination=external(), amount=1000, location=located,
                         device=current_device if registered else anchor_device,
                         status="approved" if registered else "two_factor_required",
                         reasons=() if registered else ("new_device",))
            attempts.append((moment - timedelta(minutes=float(minutes)), entry))

        wanted = int(velocity.get("attempts_24h", max(1, int((scenario.get("flow_24h") or {}).get("outflow_count", 0) or 0))))
        in_24h = [a for a in attempts if a[0] >= moment - timedelta(hours=24)]
        fill = wanted - len(in_24h)
        if fill < 0:
            notes.append(f"tentativas em 24h: o cenário pede {wanted}, os outros campos exigem {len(in_24h)}")
        for when in spread(moment - timedelta(hours=23), moment - timedelta(hours=2), max(0, fill)):
            attempts.append((when, dict(
                destination=external(), amount=1000,
                device=current_device if registered else anchor_device,
                status="approved" if registered else "rejected",
                reasons=() if registered else (NEUTRAL_REASON,),
            )))

        for when, kwargs in attempts:
            kwargs.setdefault("channel", hist_channel)
            kwargs.setdefault("ip", hist_ip)
            dest = kwargs.pop("destination")
            db.pix(when, dest, kwargs.pop("status"), payer_id, **kwargs)

        # ── O destino visto por outros clientes nossos ────────────
        for k in range(int(dest_data.get("other_clients_first_paid_7d", 0))):
            other = db.account(db.customer(RandomGenerator.cpf(), "1990-01-01"), moment - timedelta(days=400),
                               100000, 1000000, 100000)
            db.pix(moment - timedelta(days=1 + 0.5 * k), destination, "approved", other["account_id"],
                   device=f"dvc-fanin-{other['account_number']}", destination_account_id=destination.get("account_id"))
        for k in range(int(dest_data.get("other_clients_rejected_90d", 0))):
            other = db.account(db.customer(RandomGenerator.cpf(), "1990-01-01"), moment - timedelta(days=400),
                               100000, 1000000, 100000)
            db.pix(moment - timedelta(days=30 + k), destination, "rejected", other["account_id"],
                   device=f"dvc-rej-{other['account_number']}", reasons=("new_destination_account",),
                   destination_evidence=True, destination_account_id=destination.get("account_id"))

    # ── DICT (mock) ───────────────────────────────────────────────
    teach_dict(destination, dest_data.get("dict") or {}, moment)
    if (payer_data.get("dict") or {}).get("markers"):
        teach_dict(payer, payer_data["dict"], moment)

    if amount > cents(payer_data.get("balance", 5000.0)):
        notes.append("valor maior que o saldo: a API recusa antes do motor (insufficient_balance)")

    payload = {
        "id": f"replay-{scenario['id']}-{uuid4().hex[:8]}",
        "amount": amount,
        "transaction_date": iso(moment),
        "source_account": {
            "branch": payer["branch"],
            "account_number": payer["account_number"],
            "opening_date": iso(payer["opening"]),
            "owner": {"document_number": payer_document},
        },
        "destination_account": {
            "participant": destination["participant"],
            "branch": destination["branch"],
            "account_number": destination["account_number"],
            "opening_date": iso(dest_opening),
            "owner": {"document_number": dest_document},
        },
        "source": {"device_id": current_device, "channel": "app", "ip": IP},
    }
    if has_geo:
        payload["source"]["geolocation"] = dict(HERE)

    return {"payload": payload, "moment": moment, "payer": payer, "notes": notes}


def teach_dict(account: dict, data: dict, moment: datetime) -> None:
    if not data.get("available", True):
        DictMock.GET_account_connection_dropped(account)
        return

    markers = {"account": [], "owner": []}
    for item in data.get("markers") or []:
        subject = "owner" if item.get("on") == "owner" else "account"
        created = moment - timedelta(days=float(item.get("days_ago", 0)))
        markers[subject].append({"type": item.get("type", "OTHER"), "created_at": created.isoformat()})

    if markers["account"] or markers["owner"]:
        DictMock.GET_account(account, account_markers=markers["account"], owner_markers=markers["owner"])


# ── Rodar e comparar ─────────────────────────────────────────────


def analysis_of(pix_id: str) -> dict:
    with engine().connect() as connection:
        row = connection.execute(
            text(
                "SELECT s.enumerator AS status, a.features, a.decision, a.latency_ms FROM transaction_analysis a "
                "JOIN pix_transaction p ON p.id = a.pix_transaction_id "
                "JOIN analysis_status s ON s.id = a.status_id WHERE p.pix_id = :pix_id"
            ),
            {"pix_id": pix_id},
        ).mappings().first()
    return dict(row)


def signals_of(features: Features) -> dict:
    result = ScorecardEngine().evaluate(features, _FixedDict(features))
    hard = [rule["code"] for rule in result.decision.get("hard_rules", [])]
    signals = {s["code"]: s["points"] for s in result.decision.get("signals", [])}
    return {"status": result.status, "hard_rules": hard, "signals": signals}


class _FixedDict:
    def __init__(self, features: Features) -> None:
        self.answer = features.destination.dict
        features.destination.dict = None

    def __call__(self):
        return self.answer


def run(scenarios: List[dict], second_pix: bool) -> List[dict]:
    rows = []
    for i, scenario in enumerate(scenarios, 1):
        world = realize(scenario)
        payload = world["payload"]

        started = time.perf_counter()
        status_code, response = RequestGenerator.POST_pix_transaction(payload)
        client_ms = (time.perf_counter() - started) * 1000
        if status_code not in (200, 201):
            raise RuntimeError(f"{scenario['id']}: HTTP {status_code} {response}")

        analysis = analysis_of(payload["id"])
        memory = signals_of(to_features(scenario))
        row = {
            "id": scenario["id"],
            "label": scenario["label"],
            "fraud_type": scenario.get("fraud_type"),
            "operator": scenario.get("operator"),
            "difficulty": scenario.get("difficulty"),
            "source": scenario["_source"],
            "amount": payload["amount"] / 100,
            "status_api": response["status"],
            "status_memory": memory["status"],
            "client_ms": round(client_ms, 1),
            "server_ms": analysis["latency_ms"],
            "notes": world["notes"],
        }

        if analysis["features"] is not None and row["status_api"] != row["status_memory"]:
            api = signals_of(Features.from_dict(analysis["features"]))
            row["diff"] = {
                "hard_rules": {"api": api["hard_rules"], "memory": memory["hard_rules"]},
                "signals": {
                    code: {"api": api["signals"].get(code), "memory": memory["signals"].get(code)}
                    for code in sorted(set(api["signals"]) | set(memory["signals"]))
                    if api["signals"].get(code) != memory["signals"].get(code)
                },
            }
        elif analysis["features"] is None:
            row["diff"] = {"operational": [r["code"] for r in response["metadata"]["reasons"]]}

        if second_pix:
            row["second_client_ms"], row["second_server_ms"] = next_pix_latency(world)

        rows.append(row)
        mark = "" if row["status_api"] == row["status_memory"] else f"  ≠ memória {row['status_memory']}"
        print(f"[{i:3}/{len(scenarios)}] {scenario['id']:8} {row['status_api']:20} {client_ms:6.0f} ms{mark}")

    return rows


def next_pix_latency(world: dict):
    """Um segundo Pix do mesmo pagador no mesmo dia: o resumo diário e o DICT do pagador já existem."""
    payload = json.loads(json.dumps(world["payload"]))
    payload["id"] = payload["id"] + "-2"
    payload["amount"] = 100
    payload["transaction_date"] = iso(world["moment"] + timedelta(minutes=1))
    destination = external(opening=world["moment"] - timedelta(days=900))
    payload["destination_account"] = {
        "participant": destination["participant"],
        "branch": destination["branch"],
        "account_number": destination["account_number"],
        "opening_date": iso(destination["opening"]),
        "owner": {"document_number": destination["document_number"]},
    }
    started = time.perf_counter()
    RequestGenerator.POST_pix_transaction(payload)
    client_ms = (time.perf_counter() - started) * 1000
    return round(client_ms, 1), analysis_of(payload["id"])["latency_ms"]


def percentile(values: List[float], q: float) -> float:
    values = sorted(values)
    position = q * (len(values) - 1)
    low, high = math.floor(position), math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def latency(rows: List[dict]) -> dict:
    out = {}
    for key in ("client_ms", "server_ms", "second_client_ms", "second_server_ms"):
        values = [row[key] for row in rows if row.get(key) is not None]
        if values:
            out[key] = {
                "p50": round(percentile(values, 0.5)),
                "p95": round(percentile(values, 0.95)),
                "max": round(max(values)),
                "mean": round(statistics.mean(values)),
            }
    return out


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="ids de cenário")
    parser.add_argument("--no-second", action="store_true", help="sem o segundo Pix de cada pagador")
    parser.add_argument("--out", default=str(ROOT / "results" / "api_replay.json"))
    args = parser.parse_args(argv)

    scenarios = load_scenarios()
    if args.only:
        scenarios = [s for s in scenarios if s["id"] in set(args.only)]

    rows = run(scenarios, second_pix=not args.no_second)
    summary = {
        "n": len(rows),
        "latency": latency(rows),
        "same_decision": sum(1 for r in rows if r["status_api"] == r["status_memory"]),
        "api": report.scoreboard(rows, "status_api"),
        "memory": report.scoreboard(rows, "status_memory"),
    }
    Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
