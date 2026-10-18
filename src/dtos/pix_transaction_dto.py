from copy import deepcopy

from models import TransactionAnalysis


class PixTransactionDTO:
    """Traduz a análise gravada no JSON que a API devolve.

    O `metadata` não é uma coluna: é montado aqui com os motivos
    (analysis_reason), a latência e, no GET, o payload de entrada.
    """

    @staticmethod
    def analysis_to_dict(analysis: TransactionAnalysis) -> dict:
        """A resposta do POST: key, status e metadata com motivos e latência."""
        reasons = []
        for reason in analysis.reasons:
            reasons.append({"code": reason.reason_code, "message": reason.message})

        return {
            "key": analysis.analysis_key,
            "status": analysis.status.enumerator,
            "metadata": {
                "reasons": reasons,
                "latency_ms": analysis.latency_ms,
            },
        }

    @staticmethod
    def analysis_to_detail_dict(analysis: TransactionAnalysis) -> dict:
        """A resposta do GET: a do POST e o payload — o que foi pedido e o que saiu."""
        dto = PixTransactionDTO.analysis_to_dict(analysis)
        dto["metadata"]["payload"] = deepcopy(analysis.pix_transaction.payload)

        return dto
