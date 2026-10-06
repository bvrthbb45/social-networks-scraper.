from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_roles
from ..models import AuditLog, User
from ..schemas import AuditOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditOut])
def read_audit(
    action: str | None = Query(default=None, max_length=80),
    before_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_roles("auditor", "admin")),
    db: Session = Depends(get_db),
) -> list[AuditOut]:
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if action:
        q = q.where(AuditLog.action == action)
    if before_id:
        q = q.where(AuditLog.id < before_id)
    return [
        AuditOut(
            id=r.id,
            user_id=str(r.user_id) if r.user_id else None,
            action=r.action,
            object_type=r.object_type,
            object_id=r.object_id,
            ip=r.ip,
            details=r.details,
            created_at=r.created_at.isoformat(),
        )
        for r in db.scalars(q).all()
    ]
