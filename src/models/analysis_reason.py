from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from models.base import Base
from models.transaction_analysis import TransactionAnalysis


class AnalysisReason(Base):
    """Um motivo da decisão. Mais de uma regra pode disparar por Pix."""

    __tablename__ = "analysis_reason"

    id = Column(Integer, primary_key=True)
    analysis_id = Column(Integer, ForeignKey(TransactionAnalysis.id), nullable=False)
    reason_code = Column(String(50), nullable=False)
    message = Column(String(255), nullable=False)
    points = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    analysis = relationship("TransactionAnalysis", foreign_keys=[analysis_id], back_populates="reasons")
