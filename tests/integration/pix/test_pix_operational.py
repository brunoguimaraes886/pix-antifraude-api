from datetime import datetime, timedelta

from tests.utils import OUR_ISPB, SAO_PAULO, PayloadGenerator, RandomGenerator, RequestGenerator, Scenario


def reason_codes(response: dict) -> list:
    return [reason["code"] for reason in response["metadata"]["reasons"]]


class TestOperationalRejections:
    """Pix que não tem como sair do jeito que veio: rejected antes do motor.

    Todos ficam gravados (tudo que chega fica no banco) e nenhum movimenta
    saldo.
    """

    def test_unknown_payer(self):
        stranger = Scenario.external_account(participant=OUR_ISPB)
        payload = PayloadGenerator.pix(stranger, Scenario.external_account())

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201
        assert response["status"] == "rejected"
        assert reason_codes(response) == ["unknown_account"]

        analysis = Scenario.analysis(payload["id"])
        assert analysis["source_account_id"] is None
        assert analysis["features"] is None

        status, response = RequestGenerator.GET_pix_transaction(payload["id"])
        assert status == 200
        assert response["status"] == "rejected"

    def test_payer_document_is_not_the_account_owner(self):
        payer = Scenario.internal_account()
        payload = PayloadGenerator.pix(payer, Scenario.external_account())
        payload["source_account"]["owner"]["document_number"] = RandomGenerator.cpf()

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert response["status"] == "rejected"
        assert reason_codes(response) == ["account_owner_mismatch"]
        assert Scenario.balance(payer) == 500000

    def test_internal_destination_that_does_not_exist(self):
        payer = Scenario.internal_account()
        ghost = Scenario.external_account(participant=OUR_ISPB)

        status, response = RequestGenerator.POST_pix_transaction(PayloadGenerator.pix(payer, ghost))

        assert response["status"] == "rejected"
        assert reason_codes(response) == ["unknown_destination_account"]

    def test_internal_destination_with_another_owner(self):
        payer = Scenario.internal_account()
        destination = Scenario.internal_account()
        destination = dict(destination, document_number=RandomGenerator.cpf())

        status, response = RequestGenerator.POST_pix_transaction(PayloadGenerator.pix(payer, destination))

        assert response["status"] == "rejected"
        assert reason_codes(response) == ["destination_owner_mismatch"]

    def test_blocked_payer(self):
        payer = Scenario.internal_account()
        Scenario.block(payer, started_at=datetime.now(SAO_PAULO) - timedelta(days=1))

        status, response = RequestGenerator.POST_pix_transaction(PayloadGenerator.pix(payer, Scenario.external_account()))

        assert response["status"] == "rejected"
        assert reason_codes(response) == ["account_blocked"]
        assert Scenario.balance(payer) == 500000

    def test_block_that_already_ended_does_not_count(self):
        payer = Scenario.internal_account()
        now = datetime.now(SAO_PAULO)
        Scenario.block(payer, started_at=now - timedelta(days=10), ended_at=now - timedelta(days=9))

        status, response = RequestGenerator.POST_pix_transaction(PayloadGenerator.pix(payer, Scenario.external_account()))

        assert response["status"] == "approved"

    def test_insufficient_balance(self):
        payer = Scenario.internal_account(balance=5000)

        status, response = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, Scenario.external_account(), amount=5001)
        )

        assert response["status"] == "rejected"
        assert reason_codes(response) == ["insufficient_balance"]
        assert Scenario.balance(payer) == 5000

    def test_reasons_add_up(self):
        """Bloqueada E sem saldo: dois motivos, uma decisão."""
        payer = Scenario.internal_account(balance=100)
        Scenario.block(payer, started_at=datetime.now(SAO_PAULO) - timedelta(days=1))

        status, response = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, Scenario.external_account(), amount=5000)
        )

        assert response["status"] == "rejected"
        assert reason_codes(response) == ["account_blocked", "insufficient_balance"]
