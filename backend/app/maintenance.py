import uuid
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import audit
from .models import Account, Consent


def end_consent(
    db: Session, consent: Consent, new_status: str, by: uuid.UUID | None, request=None
) -> int:
    """Stop monitoring under this consent: delete its accounts (and, by cascade, their collected
    posts, findings and reviews). The consent row stays as the record of what was agreed.
    """
    from datetime import datetime, timezone

    n = len(
        db.scalars(select(Account.id).where(Account.consent_id == consent.id)).all()
    )
    db.execute(delete(Account).where(Account.consent_id == consent.id))
    consent.status = new_status
    consent.revoked_at = datetime.now(timezone.utc)
    audit.record(
        db,
        f"consent.{new_status}",
        request,
        by,
        object_type="consent",
        object_id=consent.id,
        details={"accounts_deleted": n},
    )
    return n


def expire_consents(db: Session, today: date | None = None) -> int:
    """Run daily. Expired consent == no monitoring, same effect as revocation."""
    today = today or date.today()
    due = db.scalars(
        select(Consent).where(Consent.status == "active", Consent.valid_until < today)
    ).all()
    for c in due:
        end_consent(db, c, "expired", None)
    db.commit()
    return len(due)
