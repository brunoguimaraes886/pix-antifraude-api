from datetime import date
from typing import Optional

from sqlalchemy.dialects.postgresql import insert

from database import Context
from models import AccountBaseline


class AccountBaselineRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get(self, account_id: int, baseline_date: date) -> Optional[AccountBaseline]:
        return (
            self.session.query(AccountBaseline)
            .filter(AccountBaseline.account_id == account_id, AccountBaseline.baseline_date == baseline_date)
            .first()
        )

    def insert_if_absent(self, account_id: int, baseline_date: date, values: dict) -> AccountBaseline:
        """Grava a linha do dia — a não ser que alguém tenha gravado antes.

        Dois Pix que chegam juntos no primeiro minuto do dia (um pagando,
        outro recebendo na mesma conta) calculam o resumo ao mesmo tempo.
        O ON CONFLICT DO NOTHING deixa o segundo INSERT virar nada em vez de
        estourar o UNIQUE(account_id, baseline_date); os dois leem a mesma
        linha em seguida.
        """
        statement = (
            insert(AccountBaseline)
            .values(account_id=account_id, baseline_date=baseline_date, **values)
            .on_conflict_do_nothing(index_elements=["account_id", "baseline_date"])
        )
        self.session.execute(statement)

        return self.get(account_id, baseline_date)
