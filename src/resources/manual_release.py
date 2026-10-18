from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import ManualReleaseController
from utils.schema_handler import SchemaHandler


class ManualReleaseResource:
    """A porta do operador: libera um Pix barrado e consulta a liberação."""

    @SchemaHandler.validate("post_manual_release.json")
    def on_post(self, payload: dict) -> JSONResponse:
        release = ManualReleaseController().create(payload)

        return JSONResponse(content=jsonable_encoder(release), status_code=http_status.HTTP_201_CREATED)

    def on_get_by_key(self, release_key: str) -> JSONResponse:
        release = ManualReleaseController().get_by_key(release_key)

        return JSONResponse(content=jsonable_encoder(release), status_code=http_status.HTTP_200_OK)
