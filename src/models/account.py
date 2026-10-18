from sqlalchemy import BigInteger, CHAR, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from models.base import Base
from models.customer import Customer


class Account(Base):
    """Conta corrente de um cliente nosso.

    `balance` nasce no seed e só muda com Pix aprovado. `daily_limit` vale
    para o período diurno (6h–22h) e `nightly_limit` para o noturno.
    """

    __tablename__ = "account"

    id = Column(Integer, primary_key=True)
    account_key = Column(CHAR(36), nullable=False)
    customer_id = Column(Integer, ForeignKey(Customer.id), nullable=False)
    branch = Column(String(4), nullable=False)
    account_number = Column(String(20), nullable=False)
    opening_date = Column(DateTime(timezone=True), nullable=False)
    balance = Column(BigInteger, nullable=False)
    daily_limit = Column(BigInteger, nullable=False)
    nightly_limit = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("account_key"),
        UniqueConstraint("branch", "account_number"),
    )

    customer = relationship("Customer", foreign_keys=[customer_id], lazy="selectin")
