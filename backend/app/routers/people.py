import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..deps import require_roles, uuid_or_404
from ..ingest.service import soldier_ctx
from ..maintenance import end_consent
from ..models import Account, Consent, Soldier, User
from ..security import crypto

router = APIRouter(tags=["people"])
admin_only = require_roles("admin")
can_read = require_roles(
    "admin", "reviewer"
)  # uploaders write files; they do not read names back


@router.get("/soldiers")
def list_soldiers(
    user: User = Depends(can_read), db: Session = Depends(get_db)
) -> list[dict]:
    out = []
    for s in db.scalars(select(Soldier).order_by(Soldier.created_at)).all():
        consents = db.scalars(select(Consent).where(Consent.soldier_id == s.id)).all()
        out.append(
            {
                "id": str(s.id),
                "full_name": crypto.decrypt_text(
                    s.full_name_enc, soldier_ctx(s.id, "full_name")
                ),
                "unit": (
                    crypto.decrypt_text(s.unit_enc, soldier_ctx(s.id, "unit"))
                    if s.unit_enc
                    else None
                ),
                "accounts": db.scalar(
                    select(func.count())
                    .select_from(Account)
                    .where(Account.soldier_id == s.id)
                ),
                "consents": [
                    {
                        "id": str(c.id),
                        "ref": c.document_ref,
                        "status": c.status,
                        "valid_until": c.valid_until.isoformat(),
                    }
                    for c in consents
                ],
            }
        )
    return out


@router.get("/accounts")
def list_accounts(
    user: User = Depends(can_read), db: Session = Depends(get_db)
) -> list[dict]:
    return [
        {
            "id": str(a.id),
            "soldier_id": str(a.soldier_id),
            "platform": a.platform,
            "username": a.username,
            "status": a.status,
        }
        for a in db.scalars(select(Account).order_by(Account.created_at)).all()
    ]


@router.post("/consents/{consent_id}/revoke")
def revoke_consent(
    consent_id: str,
    request: Request,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> dict:
    c = db.get(Consent, uuid_or_404(consent_id))
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if c.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Consent already {c.status}")
    n = end_consent(db, c, "revoked", user.id, request)
    db.commit()
    return {"status": "revoked", "accounts_deleted": n}


@router.delete("/soldiers/{soldier_id}", status_code=status.HTTP_204_NO_CONTENT)
def erase_soldier(
    soldier_id: str,
    request: Request,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> None:
    """Right to erasure: removes the person and, by cascade, everything collected about them."""
    s = db.get(Soldier, uuid_or_404(soldier_id))
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    sid: uuid.UUID = s.id
    db.delete(s)
    audit.record(
        db, "soldier.erased", request, user.id, object_type="soldier", object_id=sid
    )
    db.commit()
