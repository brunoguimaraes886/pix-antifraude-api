from datetime import datetime, timedelta

from tests.utils import SAO_PAULO, DictMock, PayloadGenerator, RequestGenerator, Scenario

# 23h: o período atual é a noite que começou às 22h; o anterior, o dia 6h–22h.
MOMENT = datetime(2026, 10, 14, 23, 0, tzinfo=SAO_PAULO)


def features_of(payload: dict) -> dict:
    RequestGenerator.POST_pix_transaction(payload)
    return Scenario.analysis(payload["id"])["features"]


class TestFlowFeatures:
    """Item 2 e 3 das decisões: últimas 24h e períodos diurno/noturno."""

    def test_last_24h_flow(self):
        payer = Scenario.internal_account(balance=500000)
        victim_a = Scenario.external_account()
        victim_b = Scenario.external_account()
        cash_out = Scenario.external_account()
        old_friend = Scenario.external_account()

        Scenario.statement(payer, "in", 1000, MOMENT - timedelta(days=40), counterparty=old_friend)

        Scenario.statement(payer, "in", 100000, MOMENT - timedelta(hours=20), counterparty=victim_a)
        Scenario.statement(payer, "in", 50000, MOMENT - timedelta(hours=10), counterparty=victim_b)
        Scenario.statement(payer, "in", 10000, MOMENT - timedelta(hours=9), counterparty=old_friend)
        Scenario.statement(payer, "out", 60000, MOMENT - timedelta(hours=8), counterparty=cash_out)
        Scenario.statement(payer, "out", 60000, MOMENT - timedelta(hours=1), counterparty=cash_out)

        # Fora da janela: mais de 24h antes.
        Scenario.statement(payer, "out", 5000, MOMENT - timedelta(hours=25))

        features = features_of(PayloadGenerator.pix(payer, Scenario.external_account(), transaction_date=MOMENT))
        last_24h = features["payer"]["last_24h"]

        assert last_24h["inflow"] == {
            "amount": 160000,
            "count": 3,
            "distinct_counterparties": 3,
            "new_counterparties": 2,
            "repeated_counterparties": 0,
        }
        assert last_24h["outflow"] == {
            "amount": 120000,
            "count": 2,
            "distinct_counterparties": 1,
            "new_counterparties": 1,
            "repeated_counterparties": 1,
        }
        # Saldo de agora (500000) desfazendo as 24h: +120000 que saiu, -160000 que entrou.
        assert last_24h["balance_at_start"] == 460000
        assert last_24h["pass_through_rate"] == 0.75
        assert last_24h["exit_ratio"] == round(120000 / (460000 + 160000), 4)

    def test_periods(self):
        payer = Scenario.internal_account(balance=500000, daily_limit=1000000, nightly_limit=100000)
        Scenario.statement(payer, "out", 30000, MOMENT.replace(hour=22, minute=30))
        Scenario.statement(payer, "out", 20000, MOMENT.replace(hour=15))
        Scenario.statement(payer, "in", 70000, MOMENT.replace(hour=10))
        Scenario.statement(payer, "out", 1000, MOMENT.replace(hour=5))

        features = features_of(PayloadGenerator.pix(payer, Scenario.external_account(), transaction_date=MOMENT))
        current = features["payer"]["current_period"]
        previous = features["payer"]["previous_period"]

        assert current["kind"] == "night"
        assert current["is_current"] is True
        assert current["limit"] == 100000
        assert current["start"] == "2026-10-14T22:00:00-03:00"
        assert current["end"] == "2026-10-14T23:00:00-03:00"
        assert current["outflow"]["amount"] == 30000

        assert previous["kind"] == "day"
        assert previous["is_current"] is False
        assert previous["limit"] == 1000000
        assert previous["start"] == "2026-10-14T06:00:00-03:00"
        assert previous["end"] == "2026-10-14T22:00:00-03:00"
        assert previous["outflow"]["amount"] == 20000
        assert previous["inflow"]["amount"] == 70000

    def test_pix_after_the_one_analysed_does_not_leak_into_the_window(self):
        """Um Pix com data anterior aos que já existem não vê o "futuro"."""
        payer = Scenario.internal_account(balance=500000)
        Scenario.statement(payer, "out", 40000, MOMENT + timedelta(hours=1))

        features = features_of(PayloadGenerator.pix(payer, Scenario.external_account(), transaction_date=MOMENT))

        assert features["payer"]["last_24h"]["outflow"]["amount"] == 0
        assert features["payer"]["last_24h"]["balance_at_start"] == 540000


class TestProfileFeatures:
    def test_payer_profile(self):
        payer = Scenario.internal_account(
            birth_date="1980-10-15",
            opening_date=MOMENT - timedelta(days=100),
        )

        features = features_of(
            PayloadGenerator.pix(payer, Scenario.external_account(), amount=50000, transaction_date=MOMENT)
        )

        assert features["payer"]["customer"] == {
            "document_type": "PF",
            "age_years": 45,
        }
        assert features["payer"]["account_age_days"] == 100
        assert features["transaction"]["ratio_to_balance"] == 0.1
        assert features["transaction"]["period"] == "night"
        assert features["transaction"]["local_hour"] == 23

    def test_external_destination(self):
        payer = Scenario.internal_account()
        destination = Scenario.external_account(opening_date=MOMENT - timedelta(days=7))

        features = features_of(PayloadGenerator.pix(payer, destination, transaction_date=MOMENT))
        destination_features = features["destination"]

        assert destination_features["is_internal"] is False
        assert destination_features["account"] is None
        assert destination_features["account_age_days"] == 7
        assert destination_features["dict"]["status"] == "ok"

    def test_internal_destination_brings_its_whole_profile(self):
        payer = Scenario.internal_account()
        destination = Scenario.internal_account(opening_date=MOMENT - timedelta(days=12))
        Scenario.statement(destination, "in", 90000, MOMENT - timedelta(hours=3))
        Scenario.statement(destination, "out", 85000, MOMENT - timedelta(hours=2))

        features = features_of(PayloadGenerator.pix(payer, destination, transaction_date=MOMENT))
        destination_account = features["destination"]["account"]

        assert features["destination"]["is_internal"] is True
        assert features["destination"]["account_age_days"] == 12
        assert destination_account["customer"]["document_type"] == "PF"
        assert destination_account["last_24h"]["pass_through_rate"] == round(85000 / 90000, 4)
        assert destination_account["baseline"]["history_days"] == 12


class TestHistoryFeatures:
    def test_relationship_with_the_destination(self):
        payer = Scenario.internal_account(balance=500000)
        destination = Scenario.external_account()
        Scenario.statement(payer, "out", 10000, MOMENT - timedelta(days=3), counterparty=destination)
        Scenario.statement(payer, "out", 30000, MOMENT - timedelta(days=2), counterparty=destination)
        Scenario.statement(payer, "in", 5000, MOMENT - timedelta(days=50), counterparty=destination)

        features = features_of(PayloadGenerator.pix(payer, destination, transaction_date=MOMENT))
        relationship = features["relationship"]

        assert relationship["previous_out_count"] == 2
        assert relationship["previous_out_amount"] == 40000
        assert relationship["max_previous_out_amount"] == 30000
        assert relationship["out_days_last_30d"] == 2
        assert relationship["previous_in_count"] == 1

    def test_never_paid_this_destination(self):
        payer = Scenario.internal_account()

        features = features_of(PayloadGenerator.pix(payer, Scenario.external_account(), transaction_date=MOMENT))

        assert features["relationship"]["previous_out_count"] == 0
        assert features["relationship"]["first_out_at"] is None

    def test_destination_history_counts_every_payer_of_ours(self):
        """Muitos clientes nossos pagando a mesma conta externa (sinal de laranja)."""
        destination = Scenario.external_account()

        for minutes in (30, 20, 10):
            payer = Scenario.internal_account()
            RequestGenerator.POST_pix_transaction(
                PayloadGenerator.pix(payer, destination, amount=1000, transaction_date=MOMENT - timedelta(minutes=minutes))
            )

        features = features_of(
            PayloadGenerator.pix(Scenario.internal_account(), destination, amount=1000, transaction_date=MOMENT)
        )
        history = features["destination"]["history"]

        assert history["total_count"] == 3
        assert history["approved_count"] == 3
        assert history["distinct_payers"] == 3
        assert history["last_24h_distinct_payers"] == 3
        assert history["approved_amount"] == 3000

    def test_device_velocity_and_location(self):
        payer = Scenario.internal_account(balance=500000)
        destination = Scenario.external_account()
        DictMock.GET_account_connection_dropped(destination)

        # Uma tentativa em 2FA, do aparelho de sempre, em São Paulo.
        RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(
                payer,
                destination,
                transaction_date=MOMENT - timedelta(minutes=10),
                device_id="dvc-old",
                geolocation={"latitude": -23.56, "longitude": -46.65},
            )
        )

        # Dez minutos depois: aparelho novo, no Rio.
        features = features_of(
            PayloadGenerator.pix(
                payer,
                Scenario.external_account(),
                transaction_date=MOMENT,
                device_id="dvc-new",
                geolocation={"latitude": -22.91, "longitude": -43.17},
            )
        )

        assert features["velocity"]["attempts_last_1h"] == 1
        assert features["velocity"]["attempts_current_period"] == 1
        assert features["velocity"]["seconds_since_last_attempt"] == 600

        device = features["device"]
        assert device["device_previous_uses"] == 0
        assert device["distinct_devices_last_30d"] == 1
        assert device["ip_previous_uses"] == 1
        assert 340 < device["distance_from_last_km"] < 370
        assert device["minutes_since_last_location"] == 10
