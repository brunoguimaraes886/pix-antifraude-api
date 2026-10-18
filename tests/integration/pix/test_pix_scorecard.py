"""O motor do 4.2 de ponta a ponta: as features novas que a API monta e a resposta pública."""

from datetime import datetime, timedelta

from sqlalchemy import text

from tests.utils import SAO_PAULO, DictMock, PayloadGenerator, RandomGenerator, RequestGenerator, Scenario
from tests.utils.scenario import engine

DAY_MOMENT = datetime(2026, 10, 14, 14, 0, tzinfo=SAO_PAULO)
RECENT_MULE = {"type": "MULE_ACCOUNT", "created_at": "2026-09-30T10:00:00-03:00"}


def reason_codes(response: dict) -> list:
    return [reason["code"] for reason in response["metadata"]["reasons"]]


def features_of(pix_id: str) -> dict:
    return Scenario.analysis(pix_id)["features"]


def stored_reasons(pix_id: str) -> list:
    with engine().connect() as connection:
        rows = connection.execute(
            text(
                "SELECT r.reason_code, r.points FROM analysis_reason r "
                "JOIN transaction_analysis a ON a.id = r.analysis_id "
                "JOIN pix_transaction p ON p.id = a.pix_transaction_id WHERE p.pix_id = :pix_id ORDER BY r.id"
            ),
            {"pix_id": pix_id},
        ).all()

    return [tuple(row) for row in rows]


def new_external(days: int = 900) -> dict:
    return Scenario.external_account(opening_date=DAY_MOMENT - timedelta(days=days))


class TestRestrictedLists:
    def test_sanctioned_destination_is_rejected(self):
        destination = Scenario.external_account()
        Scenario.restricted(destination["document_number"], "csnu")

        payload = PayloadGenerator.pix(Scenario.internal_account(), destination)
        _, response = RequestGenerator.POST_pix_transaction(payload)

        assert response["status"] == "rejected"
        assert reason_codes(response) == ["sanctioned_party"]
        assert Scenario.decision(payload["id"])["sanctions_freeze"] is True

    def test_sanctioned_payer_is_rejected(self):
        payer = Scenario.internal_account()
        Scenario.restricted(payer["document_number"], "csnu")

        _, response = RequestGenerator.POST_pix_transaction(PayloadGenerator.pix(payer, Scenario.external_account()))

        assert reason_codes(response) == ["sanctioned_party"]

    def test_betting_destination_is_rejected_without_consulting_the_dict(self):
        destination = Scenario.external_account(document_number=RandomGenerator.cnpj())
        Scenario.restricted(destination["document_number"], "bets")
        DictMock.GET_account(destination)

        _, response = RequestGenerator.POST_pix_transaction(PayloadGenerator.pix(Scenario.internal_account(), destination))

        assert reason_codes(response) == ["betting_destination"]
        assert DictMock.requests_for(destination) == []


class TestUnregisteredDevice:
    def test_new_device_above_200_needs_confirmation(self):
        payer = Scenario.internal_account()

        _, response = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, Scenario.external_account(), amount=30000, device_id="dvc-stranger")
        )

        assert response["status"] == "two_factor_required"
        assert "new_device_limit" in reason_codes(response)

    def test_registered_device_does_not(self):
        payer = Scenario.internal_account()

        payload = PayloadGenerator.pix(payer, Scenario.external_account(), amount=30000)
        RequestGenerator.POST_pix_transaction(payload)

        device = features_of(payload["id"])["device"]
        assert device["approved_days"] == 3
        assert device["approved_devices_count"] == 1

    def test_what_left_today_from_unregistered_devices_adds_up(self):
        payer = Scenario.internal_account()
        destination = Scenario.external_account()

        _, first = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, destination, amount=15000, transaction_date=DAY_MOMENT, device_id="dvc-a")
        )
        assert first["status"] == "approved"

        second = PayloadGenerator.pix(
            payer, destination, amount=15000, transaction_date=DAY_MOMENT + timedelta(minutes=5), device_id="dvc-b"
        )
        RequestGenerator.POST_pix_transaction(second)

        assert features_of(second["id"])["payer"]["unregistered_amount_today"] == 15000

    def test_structuring_just_below_200(self):
        payer = Scenario.internal_account()

        RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, Scenario.external_account(), amount=19900, transaction_date=DAY_MOMENT,
                                 device_id="dvc-x")
        )
        _, response = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, Scenario.external_account(), amount=19900,
                                 transaction_date=DAY_MOMENT + timedelta(minutes=30), device_id="dvc-x")
        )

        assert response["status"] == "two_factor_required"
        # Sensível a PLD: na resposta pública vira risk_policy.
        assert "new_device_structuring" not in reason_codes(response)
        assert "risk_policy" in reason_codes(response)


class TestInsistence:
    def test_same_destination_after_a_rejection_by_suspicion(self):
        payer = Scenario.internal_account()
        destination = new_external(days=60)
        DictMock.GET_account(destination, account_markers=[RECENT_MULE])

        _, first = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, destination, amount=50000, transaction_date=DAY_MOMENT)
        )
        _, second = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, destination, amount=20000, transaction_date=DAY_MOMENT + timedelta(minutes=10))
        )

        assert first["status"] == "rejected"
        assert reason_codes(second) == ["repeat_after_fraud_rejection"]
        assert len(DictMock.requests_for(destination)) == 1

    def test_a_rejection_only_by_limit_does_not_count(self):
        payer = Scenario.internal_account(daily_limit=30000)
        destination = Scenario.external_account()

        RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, destination, amount=40000, transaction_date=DAY_MOMENT)
        )
        payload = PayloadGenerator.pix(payer, destination, amount=10000, transaction_date=DAY_MOMENT + timedelta(minutes=5))
        _, response = RequestGenerator.POST_pix_transaction(payload)

        relationship = features_of(payload["id"])["relationship"]
        assert relationship["fraud_rejections_24h"] == 0
        assert relationship["blocked_attempts_24h"] == 0
        assert relationship["attempts_to_destination_24h"] == 1
        assert relationship["last_attempt_amount"] == 40000
        assert "repeat_after_fraud_rejection" not in reason_codes(response)


class TestDestinationSeenByOtherCustomers:
    def test_fan_in_counts_other_new_payers(self):
        destination = Scenario.external_account()
        for _ in range(2):
            RequestGenerator.POST_pix_transaction(
                PayloadGenerator.pix(Scenario.internal_account(), destination, amount=1000, transaction_date=DAY_MOMENT)
            )

        payload = PayloadGenerator.pix(
            Scenario.internal_account(), destination, amount=1000, transaction_date=DAY_MOMENT + timedelta(minutes=1)
        )
        RequestGenerator.POST_pix_transaction(payload)

        assert features_of(payload["id"])["destination"]["history"]["new_payers_7d"] == 2

    def test_rejection_about_the_destination_is_seen_by_the_next_customer(self):
        destination = new_external(days=60)
        DictMock.GET_account(destination, account_markers=[RECENT_MULE])

        first = PayloadGenerator.pix(Scenario.internal_account(), destination, transaction_date=DAY_MOMENT)
        RequestGenerator.POST_pix_transaction(first)
        assert Scenario.decision(first["id"])["destination_evidence"] is True

        payload = PayloadGenerator.pix(
            Scenario.internal_account(), destination, transaction_date=DAY_MOMENT + timedelta(minutes=1)
        )
        RequestGenerator.POST_pix_transaction(payload)

        assert features_of(payload["id"])["destination"]["history"]["fraud_rejected_payers_90d"] == 1


class TestRelationshipFeatures:
    def test_same_owner(self):
        document = RandomGenerator.cpf()
        payer = Scenario.internal_account(document_number=document)
        destination = Scenario.external_account(document_number=document)

        payload = PayloadGenerator.pix(payer, destination)
        RequestGenerator.POST_pix_transaction(payload)

        assert features_of(payload["id"])["relationship"]["same_owner"] is True

    def test_matching_recent_inflow_from_a_stranger(self):
        payer = Scenario.internal_account()
        Scenario.statement(payer, "in", 150000, DAY_MOMENT - timedelta(hours=2))

        payload = PayloadGenerator.pix(payer, Scenario.external_account(), amount=152000, transaction_date=DAY_MOMENT)
        RequestGenerator.POST_pix_transaction(payload)

        assert features_of(payload["id"])["relationship"]["matching_recent_inflow"] is True

    def test_previous_inflow_from_the_destination(self):
        payer = Scenario.internal_account()
        friend = Scenario.external_account()
        Scenario.statement(payer, "in", 8000, DAY_MOMENT - timedelta(days=40), counterparty=friend)

        payload = PayloadGenerator.pix(payer, friend, transaction_date=DAY_MOMENT)
        RequestGenerator.POST_pix_transaction(payload)

        relationship = features_of(payload["id"])["relationship"]
        assert relationship["previous_in_amount"] == 8000
        assert relationship["first_in_at"] is not None


class TestBaselineNightShare:
    def test_night_out_share(self):
        payer = Scenario.internal_account()
        Scenario.statement(payer, "out", 1000, DAY_MOMENT - timedelta(days=3, hours=-8))   # 22h: noite
        Scenario.statement(payer, "out", 1000, DAY_MOMENT - timedelta(days=4))             # 14h: dia

        payload = PayloadGenerator.pix(payer, Scenario.external_account(), transaction_date=DAY_MOMENT)
        RequestGenerator.POST_pix_transaction(payload)

        assert features_of(payload["id"])["payer"]["baseline"]["night_out_share"] == 0.5


class TestResponseLayers:
    def test_signals_are_stored_with_points_and_the_internal_layer_never_goes_out(self):
        payer = Scenario.internal_account()
        payload = PayloadGenerator.pix(payer, new_external(days=10), amount=480000, transaction_date=DAY_MOMENT)

        _, response = RequestGenerator.POST_pix_transaction(payload)
        _, detail = RequestGenerator.GET_pix_transaction(payload["id"])

        stored = dict(stored_reasons(payload["id"]))
        assert stored["new_destination_account"] == 30
        assert stored["first_payment_to_destination"] == 15

        for body in (response, detail):
            assert "decision" not in body["metadata"]
            assert "points" not in str(body["metadata"]["reasons"])

        decision = Scenario.decision(payload["id"])
        assert decision["points"] >= 45
        assert {"probability", "rho", "threat", "family_points", "signals"} <= set(decision)

    def test_2fa_brings_alert_and_hold(self):
        payer = Scenario.internal_account(balance=1000000, daily_limit=5000000)
        _, response = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, Scenario.external_account(), amount=800000, transaction_date=DAY_MOMENT)
        )

        assert response["status"] == "two_factor_required"
        assert response["metadata"]["alert"]
        assert response["metadata"]["hold_recommended"] is True

    def test_payer_mule_signals_go_out_as_risk_policy(self):
        payer = Scenario.internal_account(balance=500000, opening_date=DAY_MOMENT - timedelta(days=20))
        for hours in range(1, 6):
            Scenario.statement(payer, "in", 90000, DAY_MOMENT - timedelta(hours=hours))

        payload = PayloadGenerator.pix(payer, new_external(days=50), amount=440000, transaction_date=DAY_MOMENT)
        _, response = RequestGenerator.POST_pix_transaction(payload)

        stored = [code for code, _ in stored_reasons(payload["id"])]
        assert "payer_pass_through" in stored
        assert "payer_pass_through" not in reason_codes(response)
        assert "risk_policy" in reason_codes(response)
        assert Scenario.decision(payload["id"])["pld_alert"] is True
