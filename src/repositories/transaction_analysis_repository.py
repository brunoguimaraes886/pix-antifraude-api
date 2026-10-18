from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import exists, func, or_

from database import Context
from engine.reasons import Reason
from models import AnalysisReason, AnalysisStatus, PixTransaction, TransactionAnalysis
from repositories.pix_transaction_repository import destination_filter


class TransactionAnalysisRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_status(self, enumerator: str) -> AnalysisStatus:
        return self.session.query(AnalysisStatus).filter(AnalysisStatus.enumerator == enumerator).one()

    def create(
        self,
        pix: PixTransaction,
        status_enumerator: str,
        reasons: List[Reason],
        latency_ms: int,
        score: Optional[float] = None,
        features: Optional[dict] = None,
        dict_response: Optional[dict] = None,
        dict_fetched_at: Optional[datetime] = None,
        decision: Optional[dict] = None,
        alert: Optional[str] = None,
        hold_recommended: bool = False,
    ) -> TransactionAnalysis:
        analysis = TransactionAnalysis()
        analysis.analysis_key = str(uuid4())
        analysis.pix_transaction = pix
        analysis.status = self.get_status(status_enumerator)
        analysis.score = score
        analysis.latency_ms = latency_ms
        analysis.features = features
        analysis.dict_response = dict_response
        analysis.dict_fetched_at = dict_fetched_at
        analysis.decision = decision
        analysis.alert = alert
        analysis.hold_recommended = hold_recommended

        for reason in reasons:
            analysis_reason = AnalysisReason()
            analysis_reason.reason_code = reason.code
            analysis_reason.message = reason.message
            analysis_reason.points = reason.points
            analysis.reasons.append(analysis_reason)

        self.session.add(analysis)
        return analysis

    def last_with_dict_response(
        self, destination: tuple, document_number: str, exclude_pix_id: int
    ) -> Optional[TransactionAnalysis]:
        """A análise mais recente em que o DICT respondeu sobre este destino.

        "Mesmo destino" é a mesma conta OU o mesmo CPF/CNPJ: a marcação de
        fraude pode ser de qualquer um dos dois. É o fallback de quando o
        DICT não responde — a mesma cobertura de um cache, sem tabela de
        cache.
        """
        return (
            self.session.query(TransactionAnalysis)
            .join(PixTransaction, PixTransaction.id == TransactionAnalysis.pix_transaction_id)
            .filter(
                TransactionAnalysis.dict_response.isnot(None),
                PixTransaction.id != exclude_pix_id,
                or_(destination_filter(*destination), PixTransaction.destination_document_number == document_number),
            )
            .order_by(TransactionAnalysis.dict_fetched_at.desc(), TransactionAnalysis.id.desc())
            .first()
        )

    def count_rejected_as_payer(self, account_id: int, not_suspicion_codes: List[str]) -> int:
        return self._count_rejected(PixTransaction.source_account_id == account_id, not_suspicion_codes)

    def count_rejected_as_destination(self, account_id: int, not_suspicion_codes: List[str]) -> int:
        return self._count_rejected(PixTransaction.destination_account_id == account_id, not_suspicion_codes)

    def _count_rejected(self, account_condition, not_suspicion_codes: List[str]) -> int:
        """Pix rejeitados POR SUSPEITA: algum motivo que não é limite nem operacional.

        Saldo insuficiente, conta inexistente ou limite estourado não são
        sinal de fraude: não podem pesar como "Pix bloqueado" no habitual da
        conta. Basta um motivo de suspeita para contar ("todos os motivos são
        de limite ou operacionais" é o que exclui).
        """
        has_suspicion_reason = exists().where(
            AnalysisReason.analysis_id == TransactionAnalysis.id,
            AnalysisReason.reason_code.notin_(not_suspicion_codes),
        )

        return (
            self.session.query(func.count(TransactionAnalysis.id))
            .join(PixTransaction, PixTransaction.id == TransactionAnalysis.pix_transaction_id)
            .join(AnalysisStatus, AnalysisStatus.id == TransactionAnalysis.status_id)
            .filter(account_condition, AnalysisStatus.enumerator == AnalysisStatus.REJECTED, has_suspicion_reason)
            .scalar()
        )
