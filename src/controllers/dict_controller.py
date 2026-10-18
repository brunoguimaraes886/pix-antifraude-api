from datetime import datetime, timezone
from typing import Optional

from requests.exceptions import RequestException

from connectors import DictConnector
from controllers.base_controller import BaseController
from engine.features import DICT_FALLBACK, DICT_OK, DICT_UNAVAILABLE, DictFeatures
from models import PixTransaction
from repositories import TransactionAnalysisRepository


class DictController(BaseController):
    """Consulta o DICT sobre o destino do Pix — e decide o que fazer sem ele.

    (O DICT do pagador não passa por aqui a cada Pix: é consultado uma vez
    por dia, no resumo diário — veja o BaselineController.)

    Consulta a cada Pix, com prazo curto. Três desfechos:

      ok           o DICT respondeu agora;
      fallback     não respondeu: vale a resposta da última análise com o
                   mesmo destino (mesma conta ou mesmo CPF/CNPJ);
      unavailable  não respondeu e não há análise anterior: o Pix segue com
                   os outros sinais, e o que fazer com isso é do motor.

    Na análise, `dict_response` guarda só a resposta DESTA consulta (vazio =
    o DICT não respondeu). A resposta usada no fallback fica nas features.
    Assim o fallback seguinte sempre parte de uma consulta real, e nunca de
    um fallback de fallback.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.dict_connector = DictConnector()
        self.transaction_analysis_repository = TransactionAnalysisRepository(self.context)

    def consult(self, pix: PixTransaction) -> DictFeatures:
        response = self._fetch(pix)

        if response is not None:
            return DictFeatures(status=DICT_OK, response=response, fetched_at=datetime.now(timezone.utc))

        destination = (pix.destination_participant, pix.destination_branch, pix.destination_account_number)
        previous = self.transaction_analysis_repository.last_with_dict_response(
            destination, pix.destination_document_number, pix.id
        )

        if previous is not None:
            return DictFeatures(status=DICT_FALLBACK, response=previous.dict_response, fetched_at=previous.dict_fetched_at)

        return DictFeatures(status=DICT_UNAVAILABLE, response=None, fetched_at=None)

    def fetch_account(self, participant: str, branch: str, account_number: str, document_number: str) -> Optional[dict]:
        """A resposta do DICT para uma conta qualquer, ou None se ela não serve.

        Timeout e conexão caída levantam no `requests`; sem este `except`,
        o Pix inteiro viraria 500 por um problema do outro lado. Serve ao
        destino (a cada Pix) e ao pagador (uma vez por dia, no resumo diário).
        """
        try:
            response = self.dict_connector.get_account(participant, branch, account_number, document_number)
        except RequestException as exception:
            self.logger.warning(f"DICT sem resposta para a conta {branch}/{account_number}: {type(exception).__name__}")
            return None

        if response.status != 200 or not isinstance(response.json, dict):
            self.logger.warning(f"DICT respondeu {response.status} para a conta {branch}/{account_number}")
            return None

        return response.json

    def _fetch(self, pix: PixTransaction) -> Optional[dict]:
        return self.fetch_account(
            pix.destination_participant,
            pix.destination_branch,
            pix.destination_account_number,
            pix.destination_document_number,
        )
