from sqlalchemy import BigInteger, CHAR, Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from models.base import Base
from models.account import Account


class PixTransaction(Base):
    """Tudo que chegou no POST /pix/transaction — inclusive o rejeitado.

    O destino vem desmontado em colunas (e não só dentro do `payload`)
    porque é por ele que se busca: o histórico da conta de destino e o
    fallback do DICT usam os índices destas colunas.
    """

    __tablename__ = "pix_transaction"

    id = Column(Integer, primary_key=True)
    pix_id = Column(String(100), nullable=False)
    amount = Column(BigInteger, nullable=False)
    transaction_date = Column(DateTime(timezone=True), nullable=False)
    source_account_id = Column(Integer, ForeignKey(Account.id), nullable=True)
    destination_participant = Column(CHAR(8), nullable=False)
    destination_branch = Column(String(4), nullable=False)
    destination_account_number = Column(String(20), nullable=False)
    destination_opening_date = Column(DateTime(timezone=True), nullable=False)
    destination_document_number = Column(String(14), nullable=False)
    destination_account_id = Column(Integer, ForeignKey(Account.id), nullable=True)
    device_id = Column(String(100), nullable=False)
    channel = Column(String(30), nullable=False)
    ip = Column(String(45), nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    payload = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("pix_id"),)

    analysis = relationship(
        "TransactionAnalysis",
        back_populates="pix_transaction",
        uselist=False,
        lazy="selectin",
    )
