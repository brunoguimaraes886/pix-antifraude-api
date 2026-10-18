from sqlalchemy import CHAR, Column, Date, DateTime, Integer, String, UniqueConstraint, func

from models.base import Base


class Customer(Base):
    """O cliente do banco: quem é dono de uma ou mais contas.

    PF ou PJ sai do documento (11 dígitos = CPF, 14 = CNPJ), sem coluna
    própria. Para PJ, `birth_date` é a fundação.

    Sem profissão e sem renda: não há fonte confiável para elas (seriam
    autodeclaradas) e o motor se guia pelo histórico da própria conta.
    """

    __tablename__ = "customer"

    id = Column(Integer, primary_key=True)
    customer_key = Column(CHAR(36), nullable=False)
    document_number = Column(String(14), nullable=False)
    name = Column(String(255), nullable=False)
    birth_date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("customer_key"),
        UniqueConstraint("document_number"),
    )
