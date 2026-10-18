from typing import List, Optional

from database import Context
from models import Account


class AccountRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_by_branch_and_number(self, branch: str, account_number: str) -> Optional[Account]:
        return (
            self.session.query(Account)
            .filter(Account.branch == branch, Account.account_number == account_number)
            .first()
        )

    def lock(self, accounts: List[Account]) -> None:
        """Trava as contas do Pix até o commit (SELECT ... FOR UPDATE).

        Dois Pix da mesma conta ao mesmo tempo passariam os dois pela
        conferência de saldo e de limite antes de qualquer um debitar.
        Com a trava, o segundo espera o primeiro terminar e enxerga o saldo
        e o extrato já atualizados.

        A trava é sempre em ordem de id: A paga B enquanto B paga A, cada
        um travando a "sua" conta primeiro, é um deadlock. Na mesma ordem,
        um dos dois simplesmente espera.

        O `populate_existing` recarrega saldo e limites que já estavam na
        sessão: o valor que vale é o lido COM a trava.
        """
        account_ids = sorted({account.id for account in accounts})

        if not account_ids:
            return

        (
            self.session.query(Account)
            .filter(Account.id.in_(account_ids))
            .order_by(Account.id)
            .with_for_update()
            .populate_existing()
            .all()
        )

    def debit(self, account: Account, amount: int) -> None:
        account.balance = account.balance - amount

    def credit(self, account: Account, amount: int) -> None:
        account.balance = account.balance + amount
