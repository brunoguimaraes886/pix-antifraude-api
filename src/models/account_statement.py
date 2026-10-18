from sqlalchemy import BigInteger, CHAR, Column, DateTime, ForeignKey, Integer, String, func

from models.base import Base
from models.account import Account
from models.pix_transaction import PixTransaction


class AccountStatement(Base):
    """O extrato: só dinheiro que de fato moveu.

    Pix aprovado vira uma linha "out" no pagador e, se o destino for
    nosso, uma "in" no recebedor. O que veio do seed não tem
    `pix_transaction_id`.
    """

    __tablename__ = "account_statement"

    IN = "in"
    OUT = "out"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey(Account.id), nullable=False)
    direction = Column(String(3), nullable=False)
    amount = Column(BigInteger, nullable=False)
    counterparty_participant = Column(CHAR(8), nullable=False)
    counterparty_branch = Column(String(4), nullable=False)
    counterparty_account_number = Column(String(20), nullable=False)
    counterparty_document = Column(String(14), nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    pix_transaction_id = Column(Integer, ForeignKey(PixTransaction.id), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    def counterparty(self) -> tuple:
        """A identidade da contraparte: ISPB, agência e conta."""
        return (self.counterparty_participant, self.counterparty_branch, self.counterparty_account_number)
