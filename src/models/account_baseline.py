from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Integer, Numeric, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB

from models.base import Base
from models.account import Account


class AccountBaseline(Base):
    """O "habitual" da conta num dia: o resumo dos últimos 30 dias do extrato.

    Uma linha por conta por dia, gravada no primeiro Pix do dia da conta
    (src/controllers/baseline_controller.py). Os Pix seguintes do dia só
    leem. Nenhum score é salvo aqui — são dados que o motor compara com a
    transação nova. Do pagador, guarda também o DICT da própria conta,
    consultado uma vez por dia.
    """

    __tablename__ = "account_baseline"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey(Account.id), nullable=False)
    baseline_date = Column(Date, nullable=False)
    avg_out_amount = Column(BigInteger, nullable=True)
    p90_out_amount = Column(BigInteger, nullable=True)
    avg_in_amount = Column(BigInteger, nullable=True)
    p90_in_amount = Column(BigInteger, nullable=True)
    avg_daily_out_count = Column(Numeric(10, 2), nullable=True)
    avg_daily_in_count = Column(Numeric(10, 2), nullable=True)
    history_days = Column(Integer, nullable=False)
    night_out_share = Column(Numeric(5, 4), nullable=True)
    account_block_count = Column(Integer, nullable=False)
    rejected_pix_out_count = Column(Integer, nullable=False)
    rejected_pix_in_count = Column(Integer, nullable=False)
    dict_response = Column(JSONB, nullable=True)
    dict_fetched_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("account_id", "baseline_date"),)
