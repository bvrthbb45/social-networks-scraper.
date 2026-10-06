"""Learning administration. Admin only: models change what reviewers see first, so who trains,
approves and activates them is itself audited. Nothing here ever decides about a person.
"""

import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..database import get_db
from ..deps import require_roles, uuid_or_404
from ..learning import service
from ..models import FINDING_KINDS, Finding, GoldenCase, LearningModel, Review, User
from ..security import crypto

router = APIRouter(prefix="/learning", tags=["learning"])
admin_only = require_roles("admin")


class GoldenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=3, max_length=500)
    kind: str

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        if v not in FINDING_KINDS:
            raise ValueError("unknown kind")
        return v


def _model(db: Session, model_id: str) -> LearningModel:
    m = db.get(LearningModel, uuid_or_404(model_id))
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return m


def _out(db: Session, m: LearningModel) -> dict:
    return {
        "id": str(m.id),
        "version": m.version,
        "status": m.status,
        "trained_on": m.trained_on,
        "metrics": m.metrics,
        "note": m.note,
        "approvals": service.approvals(db, m),
        "created_at": m.created_at.isoformat(),
        "activated_at": m.activated_at.isoformat() if m.activated_at else None,
    }


def _fail(e: service.LearningError) -> HTTPException:
    code = (
        status.HTTP_409_CONFLICT
        if e.code not in ("insufficient_labels",)
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return HTTPException(code, e.code)


@router.get("/status")
def learning_status(
    user: User = Depends(admin_only), db: Session = Depends(get_db)
) -> dict:
    labelled = service.labeled_examples(db)
    active = service.active_model(db)
    return {
        "labels": len(labelled),
        "positives": sum(e.label for e in labelled),
        "min_labels": settings.learning_min_labels,
        "required_approvals": settings.learning_required_approvals,
        "golden_cases": len(service.golden_cases(db)),
        "active": _out(db, active) if active else None,
        "undecided_open": db.scalar(
            select(func.count())
            .select_from(Finding)
            .where(Finding.status.in_(("new", "in_review")))
        ),
    }


@router.get("/models")
def list_models(
    user: User = Depends(admin_only), db: Session = Depends(get_db)
) -> list[dict]:
    return [
        _out(db, m)
        for m in db.scalars(
            select(LearningModel).order_by(LearningModel.version.desc())
        ).all()
    ]


@router.post("/train", status_code=status.HTTP_201_CREATED)
def train(
    request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)
) -> dict:
    try:
        m = service.train_candidate(db, user.id)
    except service.LearningError as e:
        raise _fail(e)
    audit.record(
        db,
        "learning.trained",
        request,
        user.id,
        object_type="learning_model",
        object_id=m.id,
        details={
            "version": m.version,
            "labels": m.trained_on,
            "blockers": (m.metrics or {}).get("blockers", []),
        },
    )
    db.commit()
    return _out(db, m)


def _act(request, db, user, m, action: str, fn) -> dict:
    try:
        fn()
    except service.LearningError as e:
        raise _fail(e)
    audit.record(
        db,
        f"learning.{action}",
        request,
        user.id,
        object_type="learning_model",
        object_id=m.id,
        details={"version": m.version},
    )
    db.commit()
    return _out(db, m)


@router.post("/models/{model_id}/approve")
def approve(
    model_id: str,
    request: Request,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> dict:
    m = _model(db, model_id)
    return _act(
        request, db, user, m, "approved", lambda: service.approve(db, m, user.id)
    )


@router.post("/models/{model_id}/shadow")
def shadow(
    model_id: str,
    request: Request,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> dict:
    m = _model(db, model_id)
    return _act(
        request, db, user, m, "shadow_started", lambda: service.start_shadow(db, m)
    )


@router.post("/models/{model_id}/activate")
def activate(
    model_id: str,
    request: Request,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> dict:
    m = _model(db, model_id)
    return _act(request, db, user, m, "activated", lambda: service.activate(db, m))


@router.get("/models/{model_id}/shadow-report")
def shadow_report(
    model_id: str, user: User = Depends(admin_only), db: Session = Depends(get_db)
) -> dict:
    return service.shadow_report(db, _model(db, model_id))


@router.post("/rollback")
def rollback(
    request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)
) -> dict:
    try:
        to = service.rollback(db)
    except service.LearningError as e:
        raise _fail(e)
    audit.record(db, "learning.rolled_back", request, user.id, details={"to": to})
    db.commit()
    return {"to": to}


@router.get("/terms")
def term_statistics(
    user: User = Depends(admin_only), db: Session = Depends(get_db)
) -> list[dict]:
    return service.term_stats(db)


@router.get("/term-suggestions")
def term_suggestions(
    user: User = Depends(admin_only), db: Session = Depends(get_db)
) -> list[dict]:
    return service.term_suggestions(db)


@router.get("/golden")
def list_golden(
    user: User = Depends(admin_only), db: Session = Depends(get_db)
) -> list[dict]:
    return [
        {
            "id": str(g.id),
            "text": crypto.decrypt_text(g.text_enc, f"golden_cases.text:{g.id}"),
            "kind": g.kind,
        }
        for g in db.scalars(select(GoldenCase)).all()
    ]


@router.post("/golden", status_code=status.HTTP_201_CREATED)
def add_golden(
    body: GoldenIn,
    request: Request,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> dict:
    gid = uuid.uuid4()
    db.add(
        GoldenCase(
            id=gid,
            kind=body.kind,
            text_enc=crypto.encrypt_text(body.text, f"golden_cases.text:{gid}"),
            created_by=user.id,
        )
    )
    audit.record(
        db,
        "learning.golden_added",
        request,
        user.id,
        object_type="golden_case",
        object_id=gid,
    )  # never the text
    db.commit()
    return {"id": str(gid)}


@router.delete("/golden/{golden_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_golden(
    golden_id: str,
    request: Request,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> None:
    g = db.get(GoldenCase, uuid_or_404(golden_id))
    if g is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    db.delete(g)
    audit.record(
        db,
        "learning.golden_deleted",
        request,
        user.id,
        object_type="golden_case",
        object_id=golden_id,
    )
    db.commit()


_ = (Review, FINDING_KINDS)
