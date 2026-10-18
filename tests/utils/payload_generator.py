from datetime import datetime
from typing import Optional, Union

from tests.utils.random_generator import RandomGenerator
from tests.utils.scenario import SAO_PAULO, iso

DEFAULT_GEOLOCATION = {"latitude": -23.56, "longitude": -46.65}


class PayloadGenerator:
    @staticmethod
    def pix(
        source: dict,
        destination: dict,
        amount: int = 10000,
        transaction_date: Union[datetime, str, None] = None,
        pix_id: Optional[str] = None,
        device_id: Optional[str] = None,
        channel: str = "app",
        ip: str = "198.51.100.23",
        geolocation: Optional[dict] = DEFAULT_GEOLOCATION,
    ) -> dict:
        """O payload do POST /pix/transaction, no formato do enunciado.

        `source` e `destination` são as contas do Scenario. Sem data, o Pix
        acontece agora, no fuso de São Paulo.
        """
        if transaction_date is None:
            transaction_date = datetime.now(SAO_PAULO)

        if isinstance(transaction_date, datetime):
            transaction_date = iso(transaction_date)

        if pix_id is None:
            pix_id = RandomGenerator.pix_id()

        # Sem aparelho, o da própria conta (cadastrado pelo Scenario).
        if device_id is None:
            device_id = source.get("device_id", "dvc-test-1")

        payload = {
            "id": pix_id,
            "amount": amount,
            "transaction_date": transaction_date,
            "source_account": {
                "branch": source["branch"],
                "account_number": source["account_number"],
                "opening_date": source["opening_date"],
                "owner": {"document_number": source["document_number"]},
            },
            "destination_account": {
                "participant": destination["participant"],
                "branch": destination["branch"],
                "account_number": destination["account_number"],
                "opening_date": destination["opening_date"],
                "owner": {"document_number": destination["document_number"]},
            },
            "source": {
                "device_id": device_id,
                "channel": channel,
                "ip": ip,
            },
        }

        if geolocation is not None:
            payload["source"]["geolocation"] = geolocation

        return payload
