from copy import deepcopy

from engine.reasons import Reason
from engine.response import public_reasons
from models import TransactionAnalysis


class PixTransactionDTO:
    """Traduz a análise gravada no JSON que a API devolve — só a camada pública.

    O `metadata` não é uma coluna: é montado aqui com os motivos
    (analysis_reason), o alerta, a retenção recomendada, a latência e, no
    GET, o payload de entrada. Os motivos passam pelo filtro público: regras
    duras e os sinais de maior peso, com os sensíveis a PLD trocados por
    `risk_policy`. A camada interna (`decision`) nunca sai daqui.
    """

    @staticmethod
    def analysis_to_dict(analysis: TransactionAnalysis) -> dict:
        """A resposta do POST: key, status e metadata com motivos, alerta e latência."""
        stored = [Reason(reason.reason_code, reason.message, reason.points) for reason in analysis.reasons]
        reasons = [{"code": reason.code, "message": reason.message} for reason in public_reasons(stored)]

        metadata = {"reasons": reasons}
        if analysis.alert:
            metadata["alert"] = analysis.alert
        metadata["hold_recommended"] = bool(analysis.hold_recommended)
        metadata["latency_ms"] = analysis.latency_ms

        return {
            "key": analysis.analysis_key,
            "status": analysis.status.enumerator,
            "metadata": metadata,
        }

    @staticmethod
    def analysis_to_detail_dict(analysis: TransactionAnalysis) -> dict:
        """A resposta do GET: a do POST e o payload — o que foi pedido e o que saiu."""
        dto = PixTransactionDTO.analysis_to_dict(analysis)
        dto["metadata"]["payload"] = deepcopy(analysis.pix_transaction.payload)

        return dto
