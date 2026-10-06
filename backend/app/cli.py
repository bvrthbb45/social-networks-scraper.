"""Bootstrap: the first administrator is created from the server shell, never over HTTP.

python -m app.cli create-admin admin@example.org
"""

import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .config import settings
from .database import SessionLocal
from .models import Invite, User
from .security.tokens import new_opaque_token


def create_admin(email: str) -> str:
    settings.validate_secrets()
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email.lower())):
            raise SystemExit("user already exists")
        user = User(
            email=email.lower(), role="admin", password_hash="!", display_name="Admin"
        )
        db.add(user)
        db.flush()
        raw, hashed = new_opaque_token()
        db.add(
            Invite(
                user_id=user.id,
                token_hash=hashed,
                purpose="invite",
                expires_at=datetime.now(timezone.utc)
                + timedelta(hours=settings.invite_hours),
            )
        )
        db.commit()
        return raw


def make_template(kind: str, path: str) -> None:
    """Blank workbooks with the expected headers (no data), so the unit can fill them in."""
    from openpyxl import Workbook

    heads = {
        "roster": [
            "מספר אישי",
            "שם מלא",
            "יחידה",
            "פלטפורמה",
            "חשבון",
            "סטטוס",
            "אסמכתת הסכמה",
            "תאריך חתימה",
            "תוקף מ",
            "תוקף עד",
        ],
        "terms": ["מונח", "כינויים", "סוג", "חומרה"],
    }
    if kind not in heads:
        raise SystemExit("kind must be roster or terms")
    wb = Workbook()
    wb.active.append(heads[kind])
    wb.save(path)


def expire() -> int:
    from .maintenance import expire_consents

    with SessionLocal() as db:
        return expire_consents(db)


if __name__ == "__main__":
    if sys.argv[1:2] == ["analyze-pending"]:
        from .analysis.pipeline import analyze_pending

        with SessionLocal() as db:
            print(f"new findings: {analyze_pending(db)}")
        raise SystemExit(0)
    if sys.argv[1:2] == ["expire-consents"]:
        print(f"consents expired: {expire()}")
        raise SystemExit(0)
    if sys.argv[1:2] == ["make-template"] and len(sys.argv) == 4:
        make_template(sys.argv[2], sys.argv[3])
        raise SystemExit(0)
    if len(sys.argv) != 3 or sys.argv[1] != "create-admin":
        raise SystemExit(
            "usage: python -m app.cli create-admin EMAIL | expire-consents | analyze-pending | make-template roster|terms FILE"
        )
    print("One-time invitation token (valid %dh):" % settings.invite_hours)
    print(create_admin(sys.argv[2]))
