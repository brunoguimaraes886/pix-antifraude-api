from copy import deepcopy

from tests.utils import PayloadGenerator, RequestGenerator, Scenario

# O exemplo do enunciado, campo por campo. Nenhuma conta precisa existir:
# estes testes param no schema, antes da primeira consulta ao banco.
EXAMPLE = {
    "id": "pix-schema-example",
    "amount": 150000,
    "transaction_date": "2026-10-17T22:15:00-03:00",
    "source_account": {
        "branch": "0001",
        "account_number": "88213",
        "opening_date": "2025-03-02T10:00:00-03:00",
        "owner": {"document_number": "123.456.789-09"},
    },
    "destination_account": {
        "participant": "60701190",
        "branch": "3675",
        "account_number": "10442",
        "opening_date": "2026-10-10T09:00:00-03:00",
        "owner": {"document_number": "987.654.321-00"},
    },
    "source": {
        "device_id": "dvc-9f2c71a8",
        "channel": "app",
        "ip": "198.51.100.23",
        "geolocation": {"latitude": -23.56, "longitude": -46.65},
    },
}


def with_change(path: str, value) -> dict:
    """O exemplo com um campo trocado. `path` é "a.b.c"; value None apaga o campo."""
    payload = deepcopy(EXAMPLE)
    keys = path.split(".")
    target = payload
    for key in keys[:-1]:
        target = target[key]

    if value is None:
        del target[keys[-1]]
    else:
        target[keys[-1]] = value

    return payload


class TestPixSchema:
    def test_refuses_empty_body(self):
        status, response = RequestGenerator.POST_pix_transaction({})

        assert status == 400
        assert response["code"] == "QIT000001"

    def test_refuses_unknown_field(self):
        payload = deepcopy(EXAMPLE)
        payload["campo_que_nao_existe"] = 1

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 400
        assert response["code"] == "QIT000001"

    def test_every_required_field_is_required(self):
        required = [
            "id",
            "amount",
            "transaction_date",
            "source_account",
            "source_account.branch",
            "source_account.account_number",
            "source_account.opening_date",
            "source_account.owner.document_number",
            "destination_account.participant",
            "destination_account.branch",
            "destination_account.account_number",
            "destination_account.opening_date",
            "destination_account.owner.document_number",
            "source.device_id",
            "source.channel",
            "source.ip",
        ]

        for path in required:
            status, response = RequestGenerator.POST_pix_transaction(with_change(path, None))

            assert status == 400, f"o campo '{path}' não foi cobrado"
            assert response["code"] == "QIT000001"

    def test_refuses_malformed_fields(self):
        malformed = [
            ("amount", 0),
            ("amount", -100),
            ("amount", "150000"),
            ("amount", 1500.50),
            ("transaction_date", "2026-10-17T22:15:00"),
            ("transaction_date", "17/10/2026 22:15"),
            ("source_account.branch", "1"),
            ("source_account.account_number", "88-213"),
            ("source_account.owner.document_number", "123456789"),
            ("destination_account.participant", "6070119"),
            ("destination_account.owner.document_number", "987.654.321/00"),
            ("source.ip", "não é ip"),
            ("source.geolocation", {"latitude": -95, "longitude": 0}),
            ("id", "id com espaço"),
        ]

        for path, value in malformed:
            status, response = RequestGenerator.POST_pix_transaction(with_change(path, value))

            assert status == 400, f"'{path}' aceitou {value!r}"
            assert response["code"] == "QIT000001"

    def test_geolocation_is_optional(self):
        """O enunciado marca a geolocalização como opcional: ausente ou null passam."""
        payer = Scenario.internal_account()

        without_geolocation = PayloadGenerator.pix(payer, Scenario.external_account(), geolocation=None)
        status, response = RequestGenerator.POST_pix_transaction(without_geolocation)
        assert status == 201
        assert response["status"] == "approved"

        null_geolocation = PayloadGenerator.pix(payer, Scenario.external_account(), geolocation=None)
        null_geolocation["source"]["geolocation"] = None
        status, response = RequestGenerator.POST_pix_transaction(null_geolocation)
        assert status == 201
        assert response["status"] == "approved"

    def test_refuses_date_that_does_not_exist(self):
        """O schema conta dígitos, não dias: 30 de fevereiro passa nele e morre com 422."""
        status, response = RequestGenerator.POST_pix_transaction(
            with_change("transaction_date", "2026-02-30T10:00:00-03:00")
        )

        assert status == 422
        assert response["code"] == "QIT001002"

    def test_document_with_or_without_mask(self):
        """CPF com máscara e só dígitos são a mesma pessoa."""
        payer = Scenario.internal_account()
        destination = Scenario.external_account()

        payload = PayloadGenerator.pix(payer, destination)
        payload["source_account"]["owner"]["document_number"] = (
            f"{payer['document_number'][0:3]}.{payer['document_number'][3:6]}."
            f"{payer['document_number'][6:9]}-{payer['document_number'][9:11]}"
        )

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201
        assert response["status"] == "approved"
