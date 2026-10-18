from sqlalchemy import Column, Date, DateTime, Integer, String, UniqueConstraint, func

from models.base import Base


class RestrictedParty(Base):
    """Um CPF/CNPJ numa lista restritiva: sanções da ONU, apostas ou ordem judicial.

    O motor só lê o nome da lista (`csnu`, `bets`, `court_order`): as regras
    `sanctioned_party` e `betting_destination` decidem o resto.
    """

    CSNU = "csnu"
    BETS = "bets"
    COURT_ORDER = "court_order"

    __tablename__ = "restricted_party"

    id = Column(Integer, primary_key=True)
    document_number = Column(String(14), nullable=False)
    list = Column(String(20), nullable=False)
    reason = Column(String(255), nullable=False)
    listed_at = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("document_number", "list"),)
