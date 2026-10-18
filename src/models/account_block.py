from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from models.base import Base
from models.account import Account


class AccountBlock(Base):
    """Um bloqueio da própria conta. `ended_at` vazio = bloqueada agora."""

    __tablename__ = "account_block"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey(Account.id), nullable=False)
    reason = Column(String(255), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
