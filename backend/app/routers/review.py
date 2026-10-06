"""Reviewer workflow: look at a lead, see the evidence, record a decision.

Looking at evidence is itself audited (who viewed which finding / image), because the evidence is
sensitive and the audit department must be able to answer "who has seen this?".
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, media
from ..analysis import image as img_engine
from ..database import get_db
from ..deps import require_roles, uuid_or_404
from ..learning import service as learning
from ..models import Account, Finding, Import, Post, Review, User
from ..security import crypto

router = APIRouter(tags=["review"])
reviewers = require_roles("reviewer", "admin")


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["confirmed", "dismissed", "escalated"]
    reason: Literal["not_relevant", "common_word", "public_info", "other"] | None = None
    note: str | None = Field(default=None, max_length=2000)


def _get(db: Session, finding_id: str) -> tuple[Finding, Post, Account]:
    f = db.get(Finding, uuid_or_404(finding_id))
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    post = db.get(Post, f.post_id)
    return f, post, db.get(Account, post.account_id)


@router.get("/findings/{finding_id}")
def finding_detail(
    finding_id: str,
    request: Request,
    user: User = Depends(reviewers),
    db: Session = Depends(get_db),
) -> dict:
    f, post, acct = _get(db, finding_id)
    ev = (
        crypto.decrypt_json(f.evidence_enc, f"findings.evidence:{f.id}")
        if f.evidence_enc
        else {}
    )
    text = (
        crypto.decrypt_text(post.text_enc, f"posts.text:{post.id}")
        if post.text_enc
        else ""
    )
    history = []
    for r in db.scalars(
        select(Review).where(Review.finding_id == f.id).order_by(Review.decided_at)
    ).all():
        who = db.get(User, r.reviewer_id) if r.reviewer_id else None
        history.append(
            {
                "decision": r.decision,
                "reason": r.reason,
                "note": (
                    crypto.decrypt_text(r.note_enc, f"reviews.note:{r.id}")
                    if r.note_enc
                    else None
                ),
                "reviewer": (who.display_name or who.email) if who else None,
                "decided_at": r.decided_at.isoformat(),
            }
        )
    audit.record(
        db, "finding.viewed", request, user.id, object_type="finding", object_id=f.id
    )
    db.commit()
    return {
        "id": str(f.id),
        "kind": f.kind,
        "severity": f.severity,
        "score": float(f.score),
        "adjusted_score": (
            float(f.adjusted_score) if f.adjusted_score is not None else None
        ),
        "learning": learning.explain(
            db, f
        ),  # plain-Hebrew reasons behind the learned score
        "status": f.status,
        "reason": crypto.decrypt_text(f.reason_enc, f"findings.reason:{f.id}"),
        "source": ev.get("source"),
        "snippet": ev.get("snippet"),
        "engine_version": f.engine_version,
        "platform": acct.platform,
        "username": acct.username,
        "post_url": post.url,
        "posted_at": post.posted_at.isoformat() if post.posted_at else None,
        "post_text": text,
        "media": [
            {"index": i, "kind": m.get("kind")} for i, m in enumerate(post.media or [])
        ],
        "history": history,
    }


@router.get("/findings/{finding_id}/media/{index}")
def finding_media(
    finding_id: str,
    index: int,
    request: Request,
    user: User = Depends(reviewers),
    db: Session = Depends(get_db),
) -> Response:
    f, post, _ = _get(db, finding_id)
    items = post.media or []
    if not 0 <= index < len(items) or items[index].get("kind") != "image":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    try:
        data = media.load(items[index]["ref"])
        img_engine.load(data)  # never serve bytes that are not a valid image
    except (FileNotFoundError, crypto.DecryptionError, img_engine.BadImage):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    audit.record(
        db,
        "evidence.viewed",
        request,
        user.id,
        object_type="finding",
        object_id=f.id,
        details={"media_index": index},
    )
    db.commit()
    return Response(
        data,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, private",
            "Content-Disposition": "inline",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.post("/findings/{finding_id}/decision")
def decide(
    finding_id: str,
    body: DecisionIn,
    request: Request,
    user: User = Depends(reviewers),
    db: Session = Depends(get_db),
) -> dict:
    f, _, _ = _get(db, finding_id)
    if body.reason and body.decision != "dismissed":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "reason_only_for_dismissal"
        )
    rid = uuid.uuid4()
    db.add(
        Review(
            id=rid,
            finding_id=f.id,
            reviewer_id=user.id,
            decision=body.decision,
            reason=body.reason,
            note_enc=(
                crypto.encrypt_text(body.note, f"reviews.note:{rid}")
                if body.note
                else None
            ),
        )
    )
    previous = f.status
    f.status = (
        body.decision
    )  # the latest human decision is the finding's status; history is kept
    audit.record(
        db,
        "finding.decided",
        request,
        user.id,
        object_type="finding",
        object_id=f.id,
        details={
            "decision": body.decision,
            "from": previous,
            "reason": body.reason,
        },  # never the note
    )
    db.commit()
    return {"id": str(f.id), "status": f.status}


@router.get("/stats")
def stats(
    user: User = Depends(require_roles("reviewer", "admin", "auditor")),
    db: Session = Depends(get_db),
) -> dict:
    def count_by(col, where=None):
        q = select(col, func.count()).group_by(col)
        if where is not None:
            q = q.where(where)
        return {k: n for k, n in db.execute(q).all()}

    last = db.scalar(select(func.max(Import.uploaded_at)))
    return {
        "findings_by_status": count_by(Finding.status),
        "open_by_severity": count_by(
            Finding.severity, Finding.status.in_(("new", "in_review"))
        ),
        "open_by_kind": count_by(
            Finding.kind, Finding.status.in_(("new", "in_review"))
        ),
        "accounts_by_status": count_by(Account.status),
        "last_import_at": last.isoformat() if last else None,
    }


_ = Literal
