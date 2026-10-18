from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from database import Context
from engine.reasons import Reason
from models import Account, ManualRelease, PixTransaction


class ManualReleaseRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create(
        self,
        source_account: Account,
        destination: dict,
        max_amount: int,
        expires_at: datetime,
        operator: str,
        reason: str,
    ) -> ManualRelease:
        release = ManualRelease()
        release.release_key = str(uuid4())
        release.source_account = source_account
        release.destination_participant = destination["participant"]
        release.destination_branch = destination["branch"]
        release.destination_account_number = destination["account_number"]
        release.max_amount = max_amount
        release.expires_at = expires_at
        release.operator = operator
        release.reason = reason

        self.session.add(release)
        return release

    def get_by_key(self, release_key: str) -> Optional[ManualRelease]:
        return self.session.query(ManualRelease).filter(ManualRelease.release_key == release_key).first()

    def find_usable(self, pix: PixTransaction) -> Optional[ManualRelease]:
        """Uma liberação ainda não usada que cobre este Pix.

        Sem corrida: quem chama já travou a conta pagadora, então dois Pix
        do mesmo pagador não disputam a mesma liberação. Havendo mais de
        uma, gasta a que vence primeiro.
        """
        return (
            self.session.query(ManualRelease)
            .filter(
                ManualRelease.source_account_id == pix.source_account_id,
                ManualRelease.destination_participant == pix.destination_participant,
                ManualRelease.destination_branch == pix.destination_branch,
                ManualRelease.destination_account_number == pix.destination_account_number,
                ManualRelease.pix_transaction_id.is_(None),
                ManualRelease.max_amount >= pix.amount,
                ManualRelease.expires_at >= pix.transaction_date,
            )
            .order_by(ManualRelease.expires_at.asc(), ManualRelease.id.asc())
            .first()
        )

    def use(
        self, release: ManualRelease, pix: PixTransaction, status: str, reasons: List[Reason], used_at: datetime
    ) -> None:
        """Gasta a liberação, guardando o que o motor tinha decidido sem ela."""
        release.pix_transaction = pix
        release.overridden_status = status
        release.overridden_reasons = [
            {"code": reason.code, "message": reason.message, "points": reason.points} for reason in reasons
        ]
        release.used_at = used_at
