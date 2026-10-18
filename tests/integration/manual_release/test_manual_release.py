from datetime import datetime, timedelta

from tests.utils import SAO_PAULO, DictMock, PayloadGenerator, RequestGenerator, Scenario, iso

DAY_MOMENT = datetime(2026, 10, 14, 14, 0, tzinfo=SAO_PAULO)

MULE_MARKER = {"type": "MULE_ACCOUNT", "created_at": "2026-09-30T10:00:00-03:00"}


def release_payload(payer: dict, destination: dict, max_amount: int = 50000, expires_at=None) -> dict:
    payload = {
        "source_account": {"branch": payer["branch"], "account_number": payer["account_number"]},
        "destination_account": {
            "participant": destination["participant"],
            "branch": destination["branch"],
            "account_number": destination["account_number"],
        },
        "max_amount": max_amount,
        "operator": "operador.teste",
        "reason": "Cliente confirmou por telefone que o Pix é legítimo",
    }

    if expires_at is not None:
        payload["expires_at"] = iso(expires_at)

    return payload


def blocked_destination() -> dict:
    """Destino de outro banco sem DICT nem histórico: o motor pede 2FA (dict_unavailable)."""
    destination = Scenario.external_account()
    DictMock.GET_account_connection_dropped(destination)
    return destination


def reason_codes(response: dict) -> list:
    return [reason["code"] for reason in response["metadata"]["reasons"]]


class TestManualRelease:
    def test_create_and_get(self):
        payer = Scenario.internal_account()
        destination = Scenario.external_account()

        status, created = RequestGenerator.POST_manual_release(release_payload(payer, destination))

        assert status == 201
        assert created["status"] == "available"
        assert created["used_by"] is None

        status, fetched = RequestGenerator.GET_manual_release(created["key"])

        assert status == 200
        assert fetched == created

    def test_unknown_payer_is_404(self):
        payer = {"branch": "0001", "account_number": "99999999999999999999"}

        status, response = RequestGenerator.POST_manual_release(release_payload(payer, Scenario.external_account()))

        assert status == 404

    def test_releases_a_pix_blocked_by_suspicion_once(self):
        payer = Scenario.internal_account()
        destination = blocked_destination()

        _, blocked = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, destination, amount=30000, transaction_date=DAY_MOMENT)
        )
        assert blocked["status"] == "two_factor_required"

        _, release = RequestGenerator.POST_manual_release(
            release_payload(payer, destination, expires_at=DAY_MOMENT + timedelta(hours=1))
        )

        released_pix = PayloadGenerator.pix(payer, destination, amount=30000, transaction_date=DAY_MOMENT + timedelta(minutes=5))
        _, released = RequestGenerator.POST_pix_transaction(released_pix)

        assert released["status"] == "approved"
        assert reason_codes(released) == []

        _, used = RequestGenerator.GET_manual_release(release["key"])
        assert used["status"] == "used"
        assert used["used_by"]["pix_id"] == released_pix["id"]
        assert used["used_by"]["overridden_status"] == "two_factor_required"
        assert used["used_by"]["overridden_reasons"][0]["code"] == "dict_unavailable"

        # Uso único: o próximo Pix não usa a liberação. O destino agora é
        # conhecido (o Pix liberado entrou no histórico), então sai aprovado
        # pelo próprio motor, sem passar pela liberação.
        again_pix = PayloadGenerator.pix(payer, destination, amount=30000, transaction_date=DAY_MOMENT + timedelta(minutes=10))
        _, again = RequestGenerator.POST_pix_transaction(again_pix)
        assert again["status"] == "approved"
        assert "manual_release" not in Scenario.decision(again_pix["id"])

    def test_does_not_cover_a_bigger_amount(self):
        payer = Scenario.internal_account()
        destination = blocked_destination()
        RequestGenerator.POST_manual_release(
            release_payload(payer, destination, max_amount=20000, expires_at=DAY_MOMENT + timedelta(hours=1))
        )

        _, response = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, destination, amount=20001, transaction_date=DAY_MOMENT)
        )

        assert response["status"] == "two_factor_required"

    def test_expired_release_does_not_apply(self):
        payer = Scenario.internal_account()
        destination = blocked_destination()
        RequestGenerator.POST_manual_release(release_payload(payer, destination, expires_at=DAY_MOMENT))

        _, response = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, destination, amount=10000, transaction_date=DAY_MOMENT + timedelta(minutes=1))
        )

        assert response["status"] == "two_factor_required"

    def test_does_not_skip_the_limit_and_stays_available(self):
        payer = Scenario.internal_account(daily_limit=20000)
        destination = Scenario.external_account()
        _, release = RequestGenerator.POST_manual_release(
            release_payload(payer, destination, expires_at=DAY_MOMENT + timedelta(hours=1))
        )

        _, response = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, destination, amount=30000, transaction_date=DAY_MOMENT)
        )

        assert response["status"] == "rejected"
        assert reason_codes(response) == ["limit_exceeded"]

        _, still = RequestGenerator.GET_manual_release(release["key"])
        assert still["status"] == "available"

    def test_does_not_skip_a_dict_fraud_marker(self):
        payer = Scenario.internal_account()
        # Marcação recente + conta nova (o reforço): fundada suspeita pelo DICT.
        destination = Scenario.external_account(opening_date=DAY_MOMENT - timedelta(days=60))
        DictMock.GET_account(destination, account_markers=[MULE_MARKER])
        RequestGenerator.POST_manual_release(release_payload(payer, destination, expires_at=DAY_MOMENT + timedelta(hours=1)))

        _, response = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, destination, amount=10000, transaction_date=DAY_MOMENT)
        )

        assert response["status"] == "rejected"
        assert "dict_fraud_marker" in reason_codes(response)

    def test_other_destination_is_not_covered(self):
        payer = Scenario.internal_account()
        RequestGenerator.POST_manual_release(
            release_payload(payer, Scenario.external_account(), expires_at=DAY_MOMENT + timedelta(hours=1))
        )

        _, response = RequestGenerator.POST_pix_transaction(
            PayloadGenerator.pix(payer, blocked_destination(), amount=10000, transaction_date=DAY_MOMENT)
        )

        assert response["status"] == "two_factor_required"
