from connectors.rest_connector import BaseConnectorResponse, RestConnector
from constants import DICT_API_INTERNAL_TOKEN, DICT_API_TIMEOUT, DICT_API_URL


class DictConnector(RestConnector):
    """Fala com o DICT do Banco Central — no projeto, um MockServer.

    A pergunta é uma só: esta conta, ou o dono dela, tem marcação de
    fraude? A resposta esperada (o formato do mock em
    mock/dict-expectations.json):

        {
          "account": {"fraud_markers": [{"type": "MULE_ACCOUNT", "created_at": "..."}]},
          "owner":   {"fraud_markers": []}
        }

    O prazo é curto (DICT_API_TIMEOUT, 0,5 segundo por padrão): o Pix precisa
    ser decidido em poucos segundos. O que fazer quando o DICT não responde
    é decisão do DictController, não daqui.
    """

    def __init__(self) -> None:
        super().__init__(
            class_name=__name__,
            base_url=DICT_API_URL,
            timeout=DICT_API_TIMEOUT,
            internal_token=DICT_API_INTERNAL_TOKEN,
        )

    def get_account(
        self, participant: str, branch: str, account_number: str, document_number: str
    ) -> BaseConnectorResponse:
        """Consulta as marcações da conta e do CPF/CNPJ do dono.

        A conta vai no endereço; o documento vai na query string, que o
        RestConnector não escreve no log.
        """
        return self.send(
            endpoint=f"/accounts/{participant}/{branch}/{account_number}",
            method="GET",
            query_params={"document_number": document_number},
        )
