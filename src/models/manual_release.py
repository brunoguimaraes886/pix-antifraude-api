from sqlalchemy import BigInteger, CHAR, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from models.base import Base
from models.account import Account
from models.pix_transaction import PixTransaction


class ManualRelease(Base):
    """Um Pix liberado à mão por um operador, depois de o cliente reclamar.

    Vale para um pagador, um destino, até `max_amount` e até `expires_at`
    (no relógio do Pix). Uso único: `pix_transaction_id` preenchido = usada.
    """

    __tablename__ = "manual_release"

    id = Column(Integer, primary_key=True)
    release_key = Column(CHAR(36), nullable=False)
    source_account_id = Column(Integer, ForeignKey(Account.id), nullable=False)
    destination_participant = Column(CHAR(8), nullable=False)
    destination_branch = Column(String(4), nullable=False)
    destination_account_number = Column(String(20), nullable=False)
    max_amount = Column(BigInteger, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    operator = Column(String(100), nullable=False)
    reason = Column(String(255), nullable=False)
    pix_transaction_id = Column(Integer, ForeignKey(PixTransaction.id), nullable=True)
    overridden_status = Column(String(50), nullable=True)
    overridden_reasons = Column(JSONB(none_as_null=True), nullable=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("release_key"),
        UniqueConstraint("pix_transaction_id"),
    )

    source_account = relationship("Account", foreign_keys=[source_account_id], lazy="selectin")
    pix_transaction = relationship("PixTransaction", foreign_keys=[pix_transaction_id], lazy="selectin")
