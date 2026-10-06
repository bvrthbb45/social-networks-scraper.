import uuid

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditLog


def record(
    db: Session,
    action: str,
    request: Request | None = None,
    user_id: uuid.UUID | None = None,
    *,
    object_type: str | None = None,
    object_id: str | uuid.UUID | None = None,
    details: dict | None = None,
) -> None:
    """Add an audit row to the session (the caller commits).

    Never pass personal data, evidence, passwords or tokens: ``details`` is stored in
    clear text and the table is append-only.
    """
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            object_type=object_type,
            object_id=str(object_id) if object_id else None,
            ip=request.client.host if request and request.client else None,
            user_agent=(
                ((request.headers.get("user-agent") or "")[:300]) if request else None
            ),
            details=details,
        )
    )
