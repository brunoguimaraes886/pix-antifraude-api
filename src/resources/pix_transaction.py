from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import PixTransactionController
from utils.schema_handler import SchemaHandler


class PixTransactionResource:
    """A porta de entrada HTTP do Pix: confere o formato, chama o controller, responde.

    Nenhuma regra mora aqui. O único `if` é HTTP: 201 quando a análise
    nasceu agora, 200 quando o mesmo Pix chegou de novo e a análise
    gravada foi devolvida (idempotência).
    """

    @SchemaHandler.validate("post_pix_transaction.json")
    def on_post(self, payload: dict) -> JSONResponse:
        controller = PixTransactionController()
        analysis, created = controller.create(payload)

        status_code = http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK

        return JSONResponse(content=jsonable_encoder(analysis), status_code=status_code)

    def on_get_by_id(self, pix_id: str) -> JSONResponse:
        controller = PixTransactionController()
        analysis = controller.get_by_pix_id(pix_id)

        return JSONResponse(content=jsonable_encoder(analysis), status_code=http_status.HTTP_200_OK)
