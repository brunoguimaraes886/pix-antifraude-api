from tests.utils import INTERNAL_TOKEN
from tests.utils.requisition import ClientRequisition


class TestHealthCheck:
    def test_home(self):
        response = ClientRequisition.send("GET", "/")
        assert response.response_status == 200
        assert response.response_json["service"] == "pix-antifraude-api"

    def test_health_check(self):
        response = ClientRequisition.send("GET", "/health_check")
        assert response.response_status == 204

    def test_pix_routes_need_the_token(self):
        response = ClientRequisition.send("POST", "/pix/transaction", payload={})
        assert response.response_status == 403
        assert response.response_json["code"] == "QIT000002"

        response = ClientRequisition.send("GET", "/pix/transaction/pix-1")
        assert response.response_status == 403

    def test_unknown_route(self):
        response = ClientRequisition.send("GET", "/pix", headers={"INTERNAL-TOKEN": INTERNAL_TOKEN})
        assert response.response_status == 404
        assert response.response_json["code"] == "QIT000404"

    def test_method_not_allowed(self):
        response = ClientRequisition.send("PUT", "/pix/transaction", headers={"INTERNAL-TOKEN": INTERNAL_TOKEN})
        assert response.response_status == 405
        assert response.response_json["code"] == "QIT000405"
