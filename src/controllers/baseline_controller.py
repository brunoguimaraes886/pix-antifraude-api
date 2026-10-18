from datetime import datetime, timedelta
from typing import Optional

from constants import BASELINE_WINDOW_DAYS
from controllers.base_controller import BaseController
from engine.reasons import OPERATIONAL_REASONS
from models import Account, AccountBaseline, AccountStatement
from repositories import (
    AccountBaselineRepository,
    AccountBlockRepository,
    AccountStatementRepository,
    TransactionAnalysisRepository,
)
from utils.periods import local_day_start


class BaselineController(BaseController):
    """O resumo diário do histórico da conta (account_baseline).

    Calculado sob demanda: no primeiro Pix do dia da conta, se ainda não
    existe a linha de hoje, calcula e grava; os Pix seguintes do dia só
    leem. "Dia" é o dia da transação no fuso dela.

    A janela são os 30 dias ANTES do dia — o próprio dia fica de fora. É
    isso que deixa o resumo valer o dia inteiro: um Pix às 23h compara com
    o mesmo habitual que um Pix às 8h.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.account_baseline_repository = AccountBaselineRepository(self.context)
        self.account_block_repository = AccountBlockRepository(self.context)
        self.account_statement_repository = AccountStatementRepository(self.context)
        self.transaction_analysis_repository = TransactionAnalysisRepository(self.context)

    def get_or_create(self, account: Account, moment: datetime) -> AccountBaseline:
        baseline_date = moment.date()

        baseline = self.account_baseline_repository.get(account.id, baseline_date)
        if baseline is not None:
            return baseline

        self.logger.debug(f"Calculando o resumo de {baseline_date} da conta {account.account_key}")

        window_end = local_day_start(moment)
        window_start = window_end - timedelta(days=BASELINE_WINDOW_DAYS)

        out_stats = self.account_statement_repository.amount_stats(
            account.id, AccountStatement.OUT, window_start, window_end
        )
        in_stats = self.account_statement_repository.amount_stats(
            account.id, AccountStatement.IN, window_start, window_end
        )

        history_days = self._history_days(account, window_end)
        operational_codes = [reason.code for reason in OPERATIONAL_REASONS]

        values = {
            "avg_out_amount": _round(out_stats["avg"]),
            "p90_out_amount": _round(out_stats["p90"]),
            "avg_in_amount": _round(in_stats["avg"]),
            "p90_in_amount": _round(in_stats["p90"]),
            "avg_daily_out_count": _per_day(out_stats["count"], history_days),
            "avg_daily_in_count": _per_day(in_stats["count"], history_days),
            "history_days": history_days,
            "account_block_count": self.account_block_repository.count(account.id),
            "rejected_pix_out_count": self.transaction_analysis_repository.count_rejected_as_payer(
                account.id, operational_codes
            ),
            "rejected_pix_in_count": self.transaction_analysis_repository.count_rejected_as_destination(
                account.id, operational_codes
            ),
        }

        return self.account_baseline_repository.insert_if_absent(account.id, baseline_date, values)

    def _history_days(self, account: Account, window_end: datetime) -> int:
        """Quantos dias da janela a conta já existia (0 a 30).

        Uma conta de 5 dias tem 5 dias de histórico, não 30: as médias por
        dia dividem por isto, e o motor sabe o quanto confiar no resumo.
        """
        opening_day = account.opening_date.astimezone(window_end.tzinfo).date()
        days = (window_end.date() - opening_day).days

        return max(0, min(BASELINE_WINDOW_DAYS, days))


def _round(value) -> Optional[int]:
    if value is None:
        return None

    return int(round(float(value)))


def _per_day(count: int, history_days: int) -> Optional[float]:
    if history_days <= 0:
        return None

    return round(count / history_days, 2)
