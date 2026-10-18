from tests.utils import OUR_ISPB, DictMock, PayloadGenerator, RequestGenerator, Scenario


class TestPixSettlement:
    """Só o approved move dinheiro: saldo e extrato."""

    def test_approved_to_another_bank_debits_the_payer(self):
        payer = Scenario.internal_account(balance=500000)
        destination = Scenario.external_account()

        status, response = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, destination, amount=12345)
        )

        assert status == 201
        assert response["status"] == "approved"
        assert response["metadata"]["reasons"] == []
        assert Scenario.balance(payer) == 500000 - 12345

        assert Scenario.statements_from_pix(payer) == [
            {
                "direction": "out",
                "amount": 12345,
                "counterparty_participant": destination["participant"],
                "counterparty_branch": destination["branch"],
                "counterparty_account_number": destination["account_number"],
                "counterparty_document": destination["document_number"],
            }
        ]

    def test_approved_between_our_accounts_moves_both_sides(self):
        payer = Scenario.internal_account(balance=500000)
        destination = Scenario.internal_account(balance=1000)

        status, response = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, destination, amount=20000)
        )

        assert response["status"] == "approved"
        assert Scenario.balance(payer) == 480000
        assert Scenario.balance(destination) == 21000

        assert Scenario.statements_from_pix(destination) == [
            {
                "direction": "in",
                "amount": 20000,
                "counterparty_participant": OUR_ISPB,
                "counterparty_branch": payer["branch"],
                "counterparty_account_number": payer["account_number"],
                "counterparty_document": payer["document_number"],
            }
        ]

    def test_two_factor_does_not_move_money(self):
        """2FA sem retorno de confirmação = Pix não executado."""
        payer = Scenario.internal_account(balance=500000)
        destination = Scenario.external_account()
        DictMock.GET_account_connection_dropped(destination)

        status, response = RequestGenerator.POST_pix_transaction(PayloadGenerator.pix(payer, destination))

        assert response["status"] == "two_factor_required"
        assert Scenario.balance(payer) == 500000
        assert Scenario.statements_from_pix(payer) == []

    def test_same_pix_twice_is_analysed_once(self):
        """Idempotência: o mesmo id devolve a análise gravada, sem debitar de novo."""
        payer = Scenario.internal_account(balance=500000)
        payload = PayloadGenerator.pix(payer, Scenario.external_account(), amount=10000)

        first_status, first = RequestGenerator.POST_pix_transaction(payload)
        second_status, second = RequestGenerator.POST_pix_transaction(payload)

        assert first_status == 201
        assert second_status == 200
        assert second == first
        assert Scenario.balance(payer) == 490000
        assert len(Scenario.statements_from_pix(payer)) == 1

    def test_same_id_with_another_body_returns_the_first_analysis(self):
        payer = Scenario.internal_account(balance=500000)
        payload = PayloadGenerator.pix(payer, Scenario.external_account(), amount=10000)

        _, first = RequestGenerator.POST_pix_transaction(payload)

        payload["amount"] = 99999
        status, second = RequestGenerator.POST_pix_transaction(payload)

        assert status == 200
        assert second["key"] == first["key"]
        assert Scenario.balance(payer) == 490000
