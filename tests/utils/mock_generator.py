from tests.utils.mock_utils import BaseExpectation, Mock

# Mais alta que as respostas padrão de mock/dict-expectations.json: o que o
# teste ensina ganha do que o mock trouxe de casa.
TEST_PRIORITY = 100


def dict_path(account: dict) -> str:
    return f"/dict/accounts/{account['participant']}/{account['branch']}/{account['account_number']}"


def teach(account: dict, expectation: dict) -> None:
    """Ensina uma resposta para a conta, trocando a que ela tinha.

    O `id` é o da conta: ensinar de novo a mesma conta SUBSTITUI a resposta
    anterior. Sem ele, o MockServer guardaria as duas e, com a mesma
    prioridade, continuaria respondendo a mais antiga.
    """
    expectation["id"] = f"dict-{account['participant']}-{account['branch']}-{account['account_number']}"
    Mock().add_expectations(expectation)


class DictMock:
    """As respostas do DICT que o DictConnector chama.

    O mock sobe com uma resposta padrão para qualquer conta ("sem
    marcação", em mock/dict-expectations.json). Cada método aqui ensina
    uma resposta para UMA conta — a conta aleatória do teste —, então os
    testes não precisam limpar o mock e não se atrapalham.
    """

    @staticmethod
    def GET_account(account: dict, account_markers: list = None, owner_markers: list = None):
        teach(
            account,
            BaseExpectation.generate_expectation(
                "GET",
                dict_path(account),
                status_code=200,
                response_json={
                    "account": {"fraud_markers": account_markers or []},
                    "owner": {"fraud_markers": owner_markers or []},
                },
                priority=TEST_PRIORITY,
            ),
        )

    @staticmethod
    def GET_account_server_error(account: dict):
        teach(
            account,
            BaseExpectation.generate_expectation(
                "GET",
                dict_path(account),
                status_code=500,
                response_json={"code": "INTERNAL_ERROR"},
                priority=TEST_PRIORITY,
            ),
        )

    @staticmethod
    def GET_account_connection_dropped(account: dict):
        """A conexão cai sem resposta — o mesmo caminho de um DICT fora do ar."""
        teach(
            account,
            BaseExpectation.generate_error(
                "GET",
                dict_path(account),
                error_json={"dropConnection": True},
                priority=TEST_PRIORITY,
            ),
        )

    @staticmethod
    def GET_account_slow(account: dict, delay_ms: int = 3000):
        """Responde, mas depois do timeout da API (1 segundo)."""
        expectation = BaseExpectation.generate_expectation(
            "GET",
            dict_path(account),
            status_code=200,
            response_json={"account": {"fraud_markers": []}, "owner": {"fraud_markers": []}},
            priority=TEST_PRIORITY,
        )
        expectation["httpResponse"]["delay"] = {"timeUnit": "MILLISECONDS", "value": delay_ms}

        teach(account, expectation)

    @staticmethod
    def requests_for(account: dict) -> list:
        return Mock().retrieve_requests("GET", dict_path(account))
