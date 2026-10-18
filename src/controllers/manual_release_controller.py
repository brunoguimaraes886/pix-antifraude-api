from datetime import datetime, timedelta, timezone
from typing import Optional

from controllers.base_controller import BaseController
from dtos import ManualReleaseDTO
from engine import EngineResult
from engine.reasons import NOT_RELEASABLE
from engine.result import APPROVED
from errors import InvalidDateTime, NotFoundAccount, NotFoundManualRelease
from models import PixTransaction
from repositories import AccountRepository, ManualReleaseRepository

# Sem `expires_at` no pedido, a liberação vale por uma hora.
DEFAULT_VALIDITY = timedelta(hours=1)


class ManualReleaseController(BaseController):
    """A liberação manual: o operador libera um Pix que o motor barrou.

    O contato com o cliente acontece fora desta API. Aqui só existe o
    resultado dele: "este pagador pode pagar este destino, até tanto, até
    tal hora", uma vez.

    A liberação desfaz a SUSPEITA, não o limite: se o motor barrou por um
    motivo de `NOT_RELEASABLE`, ela não é usada e continua disponível.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.account_repository = AccountRepository(self.context)
        self.manual_release_repository = ManualReleaseRepository(self.context)

    def create(self, payload: dict) -> dict:
        source = payload["source_account"]
        source_account = self.account_repository.get_by_branch_and_number(source["branch"], source["account_number"])

        if source_account is None:
            raise NotFoundAccount(source["branch"], source["account_number"])

        expires_at = datetime.now(timezone.utc) + DEFAULT_VALIDITY
        if payload.get("expires_at") is not None:
            expires_at = self._parse_datetime(payload["expires_at"])

        release = self.manual_release_repository.create(
            source_account=source_account,
            destination=payload["destination_account"],
            max_amount=payload["max_amount"],
            expires_at=expires_at,
            operator=payload["operator"],
            reason=payload["reason"],
        )

        self.session.flush()
        release_dto = ManualReleaseDTO.to_dict(release)
        self.session.commit()

        self.logger.info(f"Liberação {release.release_key} criada por {release.operator}")

        return release_dto

    def get_by_key(self, release_key: str) -> dict:
        release = self.manual_release_repository.get_by_key(release_key)

        if release is None:
            raise NotFoundManualRelease(release_key)

        return ManualReleaseDTO.to_dict(release)

    def apply(self, pix: PixTransaction, result: EngineResult) -> Optional[EngineResult]:
        """A decisão nova, se uma liberação cobre este Pix barrado; senão None.

        Não faz commit: roda dentro da transação do Pix, e o uso da
        liberação só vale se a análise for gravada.
        """
        if result.status == APPROVED:
            return None

        if any(reason in NOT_RELEASABLE for reason in result.reasons):
            return None

        release = self.manual_release_repository.find_usable(pix)
        if release is None:
            return None

        self.manual_release_repository.use(release, pix, result.status, result.reasons, datetime.now(timezone.utc))
        self.logger.info(f"Pix {pix.pix_id}: {result.status} desfeito pela liberação {release.release_key}")

        return EngineResult(status=APPROVED, score=result.score)

    @staticmethod
    def _parse_datetime(raw_value: str) -> datetime:
        try:
            return datetime.fromisoformat(raw_value)
        except ValueError:
            raise InvalidDateTime("expires_at", raw_value)
