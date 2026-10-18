from typing import Optional

from database import Context
from models import RestrictedParty

# Se o documento está em mais de uma lista, vale a mais grave.
PRIORITY = (RestrictedParty.CSNU, RestrictedParty.BETS, RestrictedParty.COURT_ORDER)


class RestrictedPartyRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def list_of(self, document_number: str) -> Optional[str]:
        """A lista restritiva do CPF/CNPJ (`csnu`, `bets`, `court_order`) ou None."""
        rows = self.session.query(RestrictedParty.list).filter(RestrictedParty.document_number == document_number).all()
        lists = {row[0] for row in rows}

        for name in PRIORITY:
            if name in lists:
                return name

        return None
