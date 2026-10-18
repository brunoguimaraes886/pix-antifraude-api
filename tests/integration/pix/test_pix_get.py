from tests.utils import PayloadGenerator, RandomGenerator, RequestGenerator, Scenario


class TestPixGet:
    def test_unknown_pix_is_404(self):
        status, response = RequestGenerator.GET_pix_transaction(RandomGenerator.pix_id())

        assert status == 404
        assert response["code"] == "QIT001001"

    def test_returns_the_recorded_analysis_with_the_payload(self):
        payer = Scenario.internal_account()
        payload = PayloadGenerator.pix(payer, Scenario.external_account())

        status, created = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        status, response = RequestGenerator.GET_pix_transaction(payload["id"])

        assert status == 200
        assert response["key"] == created["key"]
        assert response["status"] == created["status"]
        assert response["metadata"]["reasons"] == created["metadata"]["reasons"]
        assert response["metadata"]["latency_ms"] == created["metadata"]["latency_ms"]
        assert response["metadata"]["payload"] == payload

    def test_post_response_follows_the_contract(self):
        payer = Scenario.internal_account()
        payload = PayloadGenerator.pix(payer, Scenario.external_account())

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201
        assert set(response.keys()) == {"key", "status", "metadata"}
        assert len(response["key"]) == 36
        assert response["status"] in ("approved", "two_factor_required", "rejected")
        assert set(response["metadata"].keys()) <= {"reasons", "alert", "hold_recommended", "latency_ms"}
        assert {"reasons", "hold_recommended", "latency_ms"} <= set(response["metadata"].keys())
        assert isinstance(response["metadata"]["latency_ms"], int)
