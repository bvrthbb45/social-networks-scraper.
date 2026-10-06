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


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "create-admin":
        raise SystemExit("usage: python -m app.cli create-admin EMAIL")
    print("One-time invitation token (valid %dh):" % settings.invite_hours)
    print(create_admin(sys.argv[2]))
