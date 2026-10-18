from models import ManualRelease


class ManualReleaseDTO:
    """A liberação manual no JSON da API: o que foi liberado e se já foi usada."""

    @staticmethod
    def to_dict(release: ManualRelease) -> dict:
        source_account = release.source_account
        pix = release.pix_transaction

        return {
            "key": release.release_key,
            "status": "used" if pix is not None else "available",
            "source_account": {
                "branch": source_account.branch,
                "account_number": source_account.account_number,
            },
            "destination_account": {
                "participant": release.destination_participant,
                "branch": release.destination_branch,
                "account_number": release.destination_account_number,
            },
            "max_amount": release.max_amount,
            "expires_at": release.expires_at.isoformat(),
            "operator": release.operator,
            "reason": release.reason,
            "used_by": None
            if pix is None
            else {
                "pix_id": pix.pix_id,
                "used_at": release.used_at.isoformat(),
                "overridden_status": release.overridden_status,
                "overridden_reasons": release.overridden_reasons,
            },
        }
