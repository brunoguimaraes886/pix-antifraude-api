from datetime import date, datetime, timedelta

from tests.utils import OUR_ISPB, SAO_PAULO, DictMock, PayloadGenerator, RequestGenerator, Scenario

MOMENT = datetime(2026, 10, 14, 14, 0, tzinfo=SAO_PAULO)
MULE_MARKER = {"type": "MULE_ACCOUNT", "created_at": "2026-09-30T10:00:00-03:00"}


class TestAccountBaseline:
    """O resumo diário: calculado no primeiro Pix do dia, lido pelos seguintes."""

    def test_first_pix_of_the_day_creates_the_summary(self):
        payer = Scenario.internal_account(opening_date=MOMENT - timedelta(days=400))
        for days_ago, amount in ((1, 10000), (2, 20000), (3, 30000), (10, 40000)):
            Scenario.statement(payer, "out", amount, MOMENT - timedelta(days=days_ago))
        Scenario.statement(payer, "in", 300000, MOMENT - timedelta(days=5))

        # Fora da janela de 30 dias: não entra.
        Scenario.statement(payer, "out", 999999, MOMENT - timedelta(days=31))
        # No próprio dia: também não entra (a janela termina na meia-noite).
        Scenario.statement(payer, "out", 777777, MOMENT - timedelta(hours=2))

        RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, Scenario.external_account(), amount=100, transaction_date=MOMENT)
        )

        baselines = Scenario.baselines(payer)
        assert len(baselines) == 1

        baseline = baselines[0]
        assert baseline["baseline_date"] == date(2026, 10, 14)
        assert baseline["avg_out_amount"] == 25000
        assert baseline["p90_out_amount"] == 37000
        assert baseline["avg_in_amount"] == 300000
        assert baseline["history_days"] == 30
        assert float(baseline["avg_daily_out_count"]) == round(4 / 30, 2)
        assert float(baseline["avg_daily_in_count"]) == round(1 / 30, 2)

    def test_later_pix_of_the_same_day_only_read(self):
        payer = Scenario.internal_account(opening_date=MOMENT - timedelta(days=400))
        Scenario.statement(payer, "out", 10000, MOMENT - timedelta(days=1))

        RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, Scenario.external_account(), amount=100, transaction_date=MOMENT)
        )

        # Movimento novo no passado depois do primeiro Pix: o resumo do dia
        # não muda.
        Scenario.statement(payer, "out", 90000, MOMENT - timedelta(days=2))

        payload = PayloadGenerator.pix(
            payer, Scenario.external_account(), amount=100, transaction_date=MOMENT + timedelta(hours=3)
        )
        RequestGenerator.POST_pix_transaction(payload)

        baselines = Scenario.baselines(payer)
        assert len(baselines) == 1
        assert baselines[0]["avg_out_amount"] == 10000

        features = Scenario.analysis(payload["id"])["features"]
        assert features["payer"]["baseline"]["avg_out_amount"] == 10000

    def test_next_day_gets_a_new_line(self):
        payer = Scenario.internal_account(opening_date=MOMENT - timedelta(days=400))

        for moment in (MOMENT, MOMENT + timedelta(days=1)):
            RequestGenerator.POST_pix_transaction(
                PayloadGenerator.pix(payer, Scenario.external_account(), amount=100, transaction_date=moment)
            )

        assert [line["baseline_date"] for line in Scenario.baselines(payer)] == [date(2026, 10, 14), date(2026, 10, 15)]

    def test_young_account_has_few_history_days(self):
        payer = Scenario.internal_account(opening_date=MOMENT - timedelta(days=5))
        Scenario.statement(payer, "in", 50000, MOMENT - timedelta(days=2))

        RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, Scenario.external_account(), amount=100, transaction_date=MOMENT)
        )

        baseline = Scenario.baselines(payer)[0]
        assert baseline["history_days"] == 5
        assert float(baseline["avg_daily_in_count"]) == 0.2
        assert baseline["avg_out_amount"] is None

    def test_no_history_at_all(self):
        payer = Scenario.internal_account(opening_date=MOMENT)

        RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, Scenario.external_account(), amount=100, transaction_date=MOMENT)
        )

        baseline = Scenario.baselines(payer)[0]
        assert baseline["history_days"] == 0
        assert baseline["avg_daily_out_count"] is None

    def test_internal_destination_also_gets_a_summary(self):
        payer = Scenario.internal_account()
        destination = Scenario.internal_account()

        RequestGenerator.POST_pix_transaction(PayloadGenerator.pix(payer, destination, amount=100))

        assert len(Scenario.baselines(destination)) == 1

    def test_blocks_and_rejected_pix_are_counted(self):
        """Pix rejeitado pelo motor conta; recusa operacional (saldo) não conta."""
        payer = Scenario.internal_account(balance=500000, opening_date=MOMENT - timedelta(days=400))
        mule = Scenario.internal_account()
        DictMock.GET_account(mule, account_markers=[MULE_MARKER])

        Scenario.block(payer, MOMENT - timedelta(days=100), MOMENT - timedelta(days=99))

        yesterday = MOMENT - timedelta(days=1)
        _, rejected = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, mule, amount=100, transaction_date=yesterday)
        )
        _, no_balance = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, Scenario.external_account(), amount=999999, transaction_date=yesterday)
        )
        assert rejected["status"] == "rejected"
        assert no_balance["metadata"]["reasons"][0]["code"] == "insufficient_balance"

        RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, Scenario.external_account(), amount=100, transaction_date=MOMENT)
        )
        today = [line for line in Scenario.baselines(payer) if line["baseline_date"] == date(2026, 10, 14)][0]
        assert today["account_block_count"] == 1
        assert today["rejected_pix_out_count"] == 1

        # Do lado de quem recebia: a conta laranja ganhou um Pix rejeitado de entrada.
        RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(mule, Scenario.external_account(), amount=100, transaction_date=MOMENT)
        )
        mule_today = [line for line in Scenario.baselines(mule) if line["baseline_date"] == date(2026, 10, 14)][0]
        assert mule_today["rejected_pix_in_count"] == 1
        assert mule["participant"] == OUR_ISPB
