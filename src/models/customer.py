from sqlalchemy import BigInteger, CHAR, Column, Date, DateTime, Integer, String, UniqueConstraint, func

from models.base import Base


class Customer(Base):
    """O cliente do banco: quem é dono de uma ou mais contas.

    PF ou PJ sai do documento (11 dígitos = CPF, 14 = CNPJ), sem coluna
    própria. Para PJ, `birth_date` é a fundação e `occupation` é o setor.
    """

    __tablename__ = "customer"

    id = Column(Integer, primary_key=True)
    customer_key = Column(CHAR(36), nullable=False)
    document_number = Column(String(14), nullable=False)
    name = Column(String(255), nullable=False)
    birth_date = Column(Date, nullable=False)
    occupation = Column(String(255), nullable=False)
    monthly_income = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("customer_key"),
        UniqueConstraint("document_number"),
    )
