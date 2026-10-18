from sqlalchemy import Boolean, CHAR, Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from models.base import Base
from models.analysis_status import AnalysisStatus
from models.pix_transaction import PixTransaction


class TransactionAnalysis(Base):
    """A decisão sobre um Pix — exatamente uma por Pix.

    O `none_as_null=True` nas duas colunas JSONB não é detalhe: sem ele, o
    SQLAlchemy grava o None do Python como o JSON `null`, e não como NULL
    do banco. Aí o "dict_response IS NOT NULL" do fallback do DICT acharia
    as análises em que o DICT não respondeu.
    """

    __tablename__ = "transaction_analysis"

    id = Column(Integer, primary_key=True)
    analysis_key = Column(CHAR(36), nullable=False)
    pix_transaction_id = Column(Integer, ForeignKey(PixTransaction.id), nullable=False)
    status_id = Column(Integer, ForeignKey(AnalysisStatus.id), nullable=False)
    score = Column(Float, nullable=True)
    latency_ms = Column(Integer, nullable=False)
    features = Column(JSONB(none_as_null=True), nullable=True)
    dict_response = Column(JSONB(none_as_null=True), nullable=True)
    dict_fetched_at = Column(DateTime(timezone=True), nullable=True)
    decision = Column(JSONB(none_as_null=True), nullable=True)
    alert = Column(String(255), nullable=True)
    hold_recommended = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("analysis_key"),
        UniqueConstraint("pix_transaction_id"),
    )

    status = relationship("AnalysisStatus", foreign_keys=[status_id], lazy="selectin")
    pix_transaction = relationship("PixTransaction", foreign_keys=[pix_transaction_id], back_populates="analysis")
    reasons = relationship(
        "AnalysisReason",
        back_populates="analysis",
        order_by="asc(AnalysisReason.id)",
        lazy="selectin",
    )
