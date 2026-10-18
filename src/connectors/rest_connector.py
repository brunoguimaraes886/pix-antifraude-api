import json
import time
from abc import ABCMeta

import requests

from utils.logger import get_logger


class RestConnector(metaclass=ABCMeta):
    """O que todo connector tem em comum: como falar com outro serviço.

    O único lugar que sabe COMO se fala com um serviço de fora:

      • o ENDEREÇO vem de configuração, nunca escrito no código;
      • o TIMEOUT é obrigatório — sem prazo, um serviço parado trava a API;
      • TODA ida e volta aparece no log, com o tempo que levou.

    Diferença para o Base Service: os parâmetros de busca viajam em
    `query_params`, separados do endpoint, e o log escreve só o endpoint.
    A consulta ao DICT leva CPF/CNPJ na query string, e documento não
    pode ir parar no log.
    """

    def __init__(self, class_name: str, base_url: str, timeout: float, internal_token: str) -> None:
        self.logger = get_logger(class_name)
        self.base_url = base_url
        self.timeout = timeout
        self.internal_token = internal_token

    def send(self, endpoint: str, method: str, payload: dict = None, headers: dict = None, query_params: dict = None):
        if headers is None:
            headers = {}

        headers["INTERNAL-TOKEN"] = self.internal_token

        url = f"{self.base_url}{endpoint}"

        self.logger.info(f"OUTGOING REQUEST {method} {url}")
        started_at = time.perf_counter()

        # Se o outro serviço demorar mais que o timeout, o requests levanta
        # um Timeout aqui: falhar rápido e com nome, em vez de esperar.
        response = requests.request(
            method.upper(),
            url,
            json=payload,
            params=query_params,
            headers=headers,
            timeout=self.timeout,
        )

        elapsed_ms = (time.perf_counter() - started_at) * 1000
        self.logger.info(f"INCOMING RESPONSE {response.status_code} {method} {url} - {elapsed_ms:.1f} ms")

        # A resposta sai COMO VEIO. Quem decide o que é erro é o controller.
        return BaseConnectorResponse(endpoint, method, response)


class BaseConnectorResponse:
    """A resposta do outro serviço, já desembrulhada."""

    def __init__(self, endpoint: str, method: str, response: requests.Response) -> None:
        self.endpoint = endpoint
        self.method = method
        self.status = response.status_code

        # Corpo que não é JSON vira None em vez de derrubar a requisição.
        self.json = None
        try:
            self.json = json.loads(response.content)
        except ValueError:
            pass
