from datetime import datetime
from typing import List, Optional, Set

from sqlalchemy import and_, distinct, func, tuple_

from database import Context
from models import AccountStatement


def counterparty_filter(participant: str, branch: str, account_number: str):
    return and_(
        AccountStatement.counterparty_participant == participant,
        AccountStatement.counterparty_branch == branch,
        AccountStatement.counterparty_account_number == account_number,
    )


class AccountStatementRepository:
    """O extrato. Só dinheiro que moveu: Pix aprovado ou histórico do seed."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create(
        self,
        account_id: int,
        direction: str,
        amount: int,
        counterparty: dict,
        occurred_at: datetime,
        pix_transaction_id: Optional[int],
    ) -> AccountStatement:
        statement = AccountStatement()
        statement.account_id = account_id
        statement.direction = direction
        statement.amount = amount
        statement.counterparty_participant = counterparty["participant"]
        statement.counterparty_branch = counterparty["branch"]
        statement.counterparty_account_number = counterparty["account_number"]
        statement.counterparty_document = counterparty["document_number"]
        statement.occurred_at = occurred_at
        statement.pix_transaction_id = pix_transaction_id

        self.session.add(statement)
        return statement

    def amount_stats(self, account_id: int, direction: str, start: datetime, end: datetime) -> dict:
        """Quantidade, média e percentil 90 dos valores de um sentido em [start, end)."""
        count, average, p90 = (
            self.session.query(
                func.count(AccountStatement.id),
                func.avg(AccountStatement.amount),
                func.percentile_cont(0.9).within_group(AccountStatement.amount),
            )
            .filter(
                AccountStatement.account_id == account_id,
                AccountStatement.direction == direction,
                AccountStatement.occurred_at >= start,
                AccountStatement.occurred_at < end,
            )
            .one()
        )

        return {"count": count, "avg": average, "p90": p90}

    def list_since(self, account_id: int, since: datetime) -> List[AccountStatement]:
        """Tudo a partir de `since` — inclusive o que veio DEPOIS do Pix analisado.

        O que veio depois não entra em janela nenhuma, mas é preciso para
        reconstruir o saldo do início da janela a partir do saldo atual.
        """
        return (
            self.session.query(AccountStatement)
            .filter(AccountStatement.account_id == account_id, AccountStatement.occurred_at >= since)
            .order_by(AccountStatement.occurred_at, AccountStatement.id)
            .all()
        )

    def counterparties_seen_before(self, account_id: int, before: datetime, candidates: Set[tuple]) -> Set[tuple]:
        """Quais destas contrapartes já apareceram no extrato antes de `before`."""
        if not candidates:
            return set()

        columns = (
            AccountStatement.counterparty_participant,
            AccountStatement.counterparty_branch,
            AccountStatement.counterparty_account_number,
        )

        rows = (
            self.session.query(*columns)
            .filter(
                AccountStatement.account_id == account_id,
                AccountStatement.occurred_at < before,
                tuple_(*columns).in_(list(candidates)),
            )
            .distinct()
            .all()
        )

        return {tuple(row) for row in rows}

    def relationship_stats(self, account_id: int, counterparty: tuple, before: datetime, since_30d: datetime) -> dict:
        """O que esta conta já fez com esta contraparte antes do Pix."""
        same_counterparty = counterparty_filter(*counterparty)

        out_count, out_amount, out_max, out_first, out_last = (
            self.session.query(
                func.count(AccountStatement.id),
                func.coalesce(func.sum(AccountStatement.amount), 0),
                func.max(AccountStatement.amount),
                func.min(AccountStatement.occurred_at),
                func.max(AccountStatement.occurred_at),
            )
            .filter(
                AccountStatement.account_id == account_id,
                AccountStatement.direction == AccountStatement.OUT,
                same_counterparty,
                AccountStatement.occurred_at < before,
            )
            .one()
        )

        out_days_last_30d = (
            self.session.query(func.count(distinct(func.date(AccountStatement.occurred_at))))
            .filter(
                AccountStatement.account_id == account_id,
                AccountStatement.direction == AccountStatement.OUT,
                same_counterparty,
                AccountStatement.occurred_at >= since_30d,
                AccountStatement.occurred_at < before,
            )
            .scalar()
        )

        in_count, in_amount, in_first = (
            self.session.query(
                func.count(AccountStatement.id),
                func.coalesce(func.sum(AccountStatement.amount), 0),
                func.min(AccountStatement.occurred_at),
            )
            .filter(
                AccountStatement.account_id == account_id,
                AccountStatement.direction == AccountStatement.IN,
                same_counterparty,
                AccountStatement.occurred_at < before,
            )
            .one()
        )

        return {
            "previous_out_count": out_count,
            "previous_out_amount": int(out_amount),
            "max_previous_out_amount": out_max,
            "first_out_at": out_first,
            "last_out_at": out_last,
            "out_days_last_30d": out_days_last_30d,
            "previous_in_count": in_count,
            "previous_in_amount": int(in_amount),
            "first_in_at": in_first,
        }

    def occurred_at_list(self, account_id: int, direction: str, start: datetime, end: datetime) -> List[datetime]:
        """Quando aconteceu cada movimento de um sentido em [start, end)."""
        rows = (
            self.session.query(AccountStatement.occurred_at)
            .filter(
                AccountStatement.account_id == account_id,
                AccountStatement.direction == direction,
                AccountStatement.occurred_at >= start,
                AccountStatement.occurred_at < end,
            )
            .all()
        )

        return [row[0] for row in rows]
