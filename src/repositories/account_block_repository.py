from datetime import datetime

from sqlalchemy import func, or_

from database import Context
from models import AccountBlock


class AccountBlockRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def is_blocked(self, account_id: int, moment: datetime) -> bool:
        """Existe um bloqueio em vigor naquele momento?

        Em vigor: começou antes e não terminou (`ended_at` vazio = bloqueada
        agora) ou termina depois.
        """
        block = (
            self.session.query(AccountBlock.id)
            .filter(
                AccountBlock.account_id == account_id,
                AccountBlock.started_at <= moment,
                or_(AccountBlock.ended_at.is_(None), AccountBlock.ended_at > moment),
            )
            .first()
        )

        return block is not None

    def count(self, account_id: int) -> int:
        return self.session.query(func.count(AccountBlock.id)).filter(AccountBlock.account_id == account_id).scalar()
