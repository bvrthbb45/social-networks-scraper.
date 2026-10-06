from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from .. import audit, reports
from ..database import get_db
from ..deps import require_roles
from ..models import User

router = APIRouter(prefix="/reports", tags=["reports"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXPORTABLE = ("confirmed", "escalated", "dismissed")


@router.get("/summary")
def summary(
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(require_roles("admin", "auditor")),
    db: Session = Depends(get_db),
) -> dict:
    return reports.summary(db, days)


@router.get("/retention")
def retention(
    user: User = Depends(require_roles("admin", "auditor")),
    db: Session = Depends(get_db),
) -> dict:
    return reports.retention_status(db)


@router.get("/consents")
def consents(
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> list[dict]:
    return reports.consents_expiring(db, days)


@router.get("/export/findings")
def export_findings(
    request: Request,
    states: str = Query(default="confirmed,escalated"),
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(require_roles("admin", "reviewer")),
    db: Session = Depends(get_db),
) -> Response:
    chosen = tuple(s for s in dict.fromkeys(x.strip() for x in states.split(",")) if s)
    if not chosen or any(s not in EXPORTABLE for s in chosen):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "bad_states")
    data, n = reports.export_findings(db, user, chosen, days)
    audit.record(
        db,
        "report.exported",
        request,
        user.id,
        details={"report": "findings", "rows": n, "states": list(chosen), "days": days},
    )
    db.commit()
    return Response(
        data,
        media_type=XLSX,
        headers={
            "Content-Disposition": 'attachment; filename="findings-report.xlsx"',
            "Cache-Control": "no-store",
        },
    )
