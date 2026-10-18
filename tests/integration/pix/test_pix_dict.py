import time
from datetime import datetime, timedelta

from tests.utils import SAO_PAULO, DictMock, PayloadGenerator, RandomGenerator, RequestGenerator, Scenario

MULE_MARKER = {"type": "MULE_ACCOUNT", "created_at": "2026-09-30T10:00:00-03:00"}


def dict_features(pix_id: str) -> dict:
    return Scenario.analysis(pix_id)["features"]["destination"]["dict"]


class TestDictConsultation:
    def test_response_is_recorded_in_the_analysis(self):
        payer = Scenario.internal_account()
        destination = Scenario.external_account()
        DictMock.GET_account(destination, account_markers=[MULE_MARKER])

        payload = PayloadGenerator.pix(payer, destination)
        RequestGenerator.POST_pix_transaction(payload)

        analysis = Scenario.analysis(payload["id"])
        assert analysis["dict_response"]["account"]["fraud_markers"] == [MULE_MARKER]
        assert analysis["dict_fetched_at"] is not None
        assert analysis["features"]["destination"]["dict"]["status"] == "ok"

    def test_document_goes_in_the_query_string(self):
        payer = Scenario.internal_account()
        destination = Scenario.external_account()
        DictMock.GET_account(destination)

        RequestGenerator.POST_pix_transaction(PayloadGenerator.pix(payer, destination))

        requests = DictMock.requests_for(destination)
        assert len(requests) == 1
        assert requests[0]["queryStringParameters"]["document_number"] == [destination["document_number"]]

    def test_dict_is_also_consulted_for_our_own_accounts(self):
        payer = Scenario.internal_account()
        destination = Scenario.internal_account()
        DictMock.GET_account(destination)

        RequestGenerator.POST_pix_transaction(PayloadGenerator.pix(payer, destination))

        assert len(DictMock.requests_for(destination)) == 1


class TestDictFallback:
    """DICT fora do ar: vale a última análise do mesmo destino (conta ou CPF/CNPJ)."""

    def test_uses_the_last_analysis_of_the_same_account(self):
        # Conta nova: a marcação recente do DICT tem o reforço e rejeita.
        destination = Scenario.external_account(opening_date=datetime.now(SAO_PAULO) - timedelta(days=60))

        DictMock.GET_account(destination, account_markers=[MULE_MARKER])
        RequestGenerator.POST_pix_transaction(PayloadGenerator.pix(Scenario.internal_account(), destination))

        # Outro pagador: o mesmo pagador nem chegaria ao DICT (insistência
        # depois de uma rejeição por suspeita rejeita antes).
        DictMock.GET_account_connection_dropped(destination)
        payload = PayloadGenerator.pix(Scenario.internal_account(), destination)
        status, response = RequestGenerator.POST_pix_transaction(payload)

        features = dict_features(payload["id"])
        assert features["status"] == "fallback"
        assert features["response"]["account"]["fraud_markers"] == [MULE_MARKER]

        # O que vale do fallback continua valendo para o motor...
        assert response["status"] == "rejected"

        # ...mas a análise registra que o DICT não respondeu desta vez.
        analysis = Scenario.analysis(payload["id"])
        assert analysis["dict_response"] is None
        assert analysis["dict_fetched_at"] is None

    def test_uses_the_last_analysis_of_the_same_document(self):
        """A marcação pode ser do CPF: outra conta do mesmo dono serve de fallback."""
        payer = Scenario.internal_account()
        owner_document = RandomGenerator.cpf()
        first_account = Scenario.external_account(document_number=owner_document)
        second_account = Scenario.external_account(document_number=owner_document)

        DictMock.GET_account(first_account, owner_markers=[MULE_MARKER])
        RequestGenerator.POST_pix_transaction(PayloadGenerator.pix(payer, first_account))

        DictMock.GET_account_server_error(second_account)
        payload = PayloadGenerator.pix(payer, second_account)
        RequestGenerator.POST_pix_transaction(payload)

        features = dict_features(payload["id"])
        assert features["status"] == "fallback"
        assert features["response"]["owner"]["fraud_markers"] == [MULE_MARKER]

    def test_fallback_never_chains_on_another_fallback(self):
        """A análise que usou fallback não guarda dict_response: o próximo
        fallback ainda parte da última consulta real."""
        payer = Scenario.internal_account()
        destination = Scenario.external_account()

        DictMock.GET_account(destination)
        first = PayloadGenerator.pix(payer, destination)
        RequestGenerator.POST_pix_transaction(first)
        real_fetch = Scenario.analysis(first["id"])["dict_fetched_at"]

        DictMock.GET_account_connection_dropped(destination)
        for _ in range(2):
            payload = PayloadGenerator.pix(payer, destination)
            RequestGenerator.POST_pix_transaction(payload)

        assert dict_features(payload["id"])["fetched_at"] == real_fetch.isoformat()

    def test_no_answer_and_no_history_is_unavailable(self):
        payer = Scenario.internal_account()
        destination = Scenario.external_account()
        DictMock.GET_account_connection_dropped(destination)

        payload = PayloadGenerator.pix(payer, destination)
        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert dict_features(payload["id"]) == {"status": "unavailable", "response": None, "fetched_at": None}
        assert response["status"] == "two_factor_required"
        assert response["metadata"]["reasons"][0]["code"] == "dict_unavailable"

    def test_slow_dict_does_not_hold_the_pix(self):
        """O DICT demora 3s; a API desiste em 1s e decide sem ele."""
        payer = Scenario.internal_account()
        destination = Scenario.external_account()
        DictMock.GET_account_slow(destination, delay_ms=3000)

        payload = PayloadGenerator.pix(payer, destination)
        started_at = time.perf_counter()
        status, response = RequestGenerator.POST_pix_transaction(payload)
        elapsed = time.perf_counter() - started_at

        assert status == 201
        assert elapsed < 2.5
        assert dict_features(payload["id"])["status"] == "unavailable"


class TestPayerDict:
    """O DICT da conta que envia: uma consulta por dia, guardada no resumo diário."""

    def test_marked_payer_with_a_new_account_is_rejected(self):
        payer = Scenario.internal_account(opening_date=datetime.now(SAO_PAULO) - timedelta(days=12))
        DictMock.GET_account(payer, owner_markers=[MULE_MARKER])

        payload = PayloadGenerator.pix(payer, Scenario.external_account())
        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert response["status"] == "rejected"
        # Sigilo: o cliente não fica sabendo da suspeita de lavagem.
        assert [reason["code"] for reason in response["metadata"]["reasons"]] == ["risk_policy"]

        hard_rules = Scenario.decision(payload["id"])["hard_rules"]
        assert {"code": "payer_dict_fraud_marker", "status": "rejected"} in hard_rules
        assert Scenario.analysis(payload["id"])["features"]["payer"]["dict"]["status"] == "ok"

    def test_payer_dict_is_consulted_once_a_day(self):
        payer = Scenario.internal_account()
        DictMock.GET_account(payer)

        for _ in range(2):
            RequestGenerator.POST_pix_transaction(PayloadGenerator.pix(payer, Scenario.external_account()))

        assert len(DictMock.requests_for(payer)) == 1
        assert Scenario.baselines(payer)[-1]["dict_fetched_at"] is not None

    def test_payer_dict_down_is_retried_on_the_next_pix(self):
        payer = Scenario.internal_account()
        DictMock.GET_account_server_error(payer)

        first = PayloadGenerator.pix(payer, Scenario.external_account())
        RequestGenerator.POST_pix_transaction(first)
        assert Scenario.analysis(first["id"])["features"]["payer"]["dict"]["status"] == "unavailable"

        DictMock.GET_account(payer)
        second = PayloadGenerator.pix(payer, Scenario.external_account())
        RequestGenerator.POST_pix_transaction(second)
        assert Scenario.analysis(second["id"])["features"]["payer"]["dict"]["status"] == "ok"
