from datetime import datetime, timedelta

from tests.utils import SAO_PAULO, DictMock, PayloadGenerator, RequestGenerator, Scenario

# Momentos fixos: os períodos (diurno 6h–22h, noturno 22h–6h) dependem da hora.
DAY_MOMENT = datetime(2026, 10, 14, 14, 0, tzinfo=SAO_PAULO)
NIGHT_MOMENT = datetime(2026, 10, 14, 23, 0, tzinfo=SAO_PAULO)

MULE_MARKER = {"type": "MULE_ACCOUNT", "created_at": "2026-09-30T10:00:00-03:00"}


def reason_codes(response: dict) -> list:
    return [reason["code"] for reason in response["metadata"]["reasons"]]


class TestEngineRulesThroughTheApi:
    """As regras do motor provisório, de ponta a ponta: payload → decisão gravada."""

    def test_night_limit_counts_what_already_left_tonight(self):
        payer = Scenario.internal_account(nightly_limit=100000)
        Scenario.statement(payer, "out", 80000, NIGHT_MOMENT - timedelta(minutes=30))

        status, response = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, Scenario.external_account(), amount=30000, transaction_date=NIGHT_MOMENT)
        )

        assert response["status"] == "rejected"
        assert reason_codes(response) == ["limit_exceeded"]

    def test_limit_exceeded_does_not_consult_the_dict(self):
        payer = Scenario.internal_account(nightly_limit=100000)
        destination = Scenario.external_account()
        DictMock.GET_account(destination)

        status, response = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, destination, amount=150000, transaction_date=NIGHT_MOMENT)
        )

        assert response["status"] == "rejected"
        assert DictMock.requests_for(destination) == []

    def test_what_left_during_the_day_does_not_eat_the_night_limit(self):
        payer = Scenario.internal_account(nightly_limit=100000)
        Scenario.statement(payer, "out", 80000, NIGHT_MOMENT.replace(hour=19))

        status, response = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, Scenario.external_account(), amount=30000, transaction_date=NIGHT_MOMENT)
        )

        assert response["status"] == "approved"

    def test_day_limit(self):
        payer = Scenario.internal_account(daily_limit=200000, balance=1000000)

        status, response = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, Scenario.external_account(), amount=200001, transaction_date=DAY_MOMENT)
        )

        assert response["status"] == "rejected"
        assert reason_codes(response) == ["limit_exceeded"]

    def test_approved_pix_eats_the_limit_of_the_next_one(self):
        """O primeiro Pix aprovado entra no extrato e conta pro limite do segundo."""
        payer = Scenario.internal_account(nightly_limit=100000)
        destination = Scenario.external_account()

        _, first = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, destination, amount=60000, transaction_date=NIGHT_MOMENT)
        )
        _, second = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(
                payer, destination, amount=60000, transaction_date=NIGHT_MOMENT + timedelta(minutes=5)
            )
        )

        assert first["status"] == "approved"
        assert second["status"] == "rejected"
        assert reason_codes(second) == ["limit_exceeded"]

    def test_dict_fraud_marker_rejects(self):
        payer = Scenario.internal_account()
        destination = Scenario.external_account(opening_date=DAY_MOMENT - timedelta(days=60))
        DictMock.GET_account(destination, account_markers=[MULE_MARKER])

        status, response = RequestGenerator.POST_pix_transaction(PayloadGenerator.pix(payer, destination))

        assert response["status"] == "rejected"
        assert reason_codes(response)[0] == "dict_fraud_marker"

    def test_dict_marker_on_the_owner_also_rejects(self):
        payer = Scenario.internal_account()
        destination = Scenario.external_account(opening_date=DAY_MOMENT - timedelta(days=60))
        DictMock.GET_account(destination, owner_markers=[MULE_MARKER])

        status, response = RequestGenerator.POST_pix_transaction(PayloadGenerator.pix(payer, destination))

        assert response["status"] == "rejected"

    def test_rejected_by_the_engine_does_not_move_money(self):
        payer = Scenario.internal_account(balance=500000)
        destination = Scenario.external_account()
        DictMock.GET_account(destination, account_markers=[MULE_MARKER])

        RequestGenerator.POST_pix_transaction(PayloadGenerator.pix(payer, destination))

        assert Scenario.balance(payer) == 500000
        assert Scenario.statements_from_pix(payer) == []
