from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..analysis import pipeline
from ..database import get_db
from ..deps import require_roles
from ..ingest import posts as intake
from ..limiter import limiter
from ..models import Account, Finding, Post, User
from ..security import crypto

router = APIRouter(tags=["posts"])
MAX_BODY = 40 * 1024 * 1024


class ItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_id: str | None = Field(default=None, max_length=120)
    url: str | None = Field(default=None, max_length=500)
    posted_at: datetime | None = None
    text: str | None = Field(default=None, max_length=intake.MAX_TEXT)
    images: list[str] = Field(
        default_factory=list, max_length=intake.MAX_IMAGES + 1
    )  # base64


class PostsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Literal["instagram", "tiktok", "facebook"]
    username: str = Field(min_length=1, max_length=100)
    items: list[ItemIn] = Field(min_length=1, max_length=20)


@router.post("/posts/import")
@limiter.limit("30/minute")
def import_posts(
    request: Request,
    body: PostsIn,
    user: User = Depends(require_roles("uploader", "admin")),
    db: Session = Depends(get_db),
) -> dict:
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "body_too_large")
    try:
        account, _ = intake.find_account(db, body.platform, body.username)
    except intake.Rejected as e:
        audit.record(db, "posts.refused", request, user.id, details={"reason": e.code})
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, e.code)
    created = duplicates = 0
    rejected: dict[str, int] = {}
    new_posts = []
    for item in body.items:
        try:
            post = intake.add_post(db, account, item.model_dump())
        except intake.Rejected as e:
            rejected[e.code] = rejected.get(e.code, 0) + 1
            continue
        if post is None:
            duplicates += 1
        else:
            created += 1
            new_posts.append(post)
    terms = pipeline.load_terms(db)
    findings = sum(pipeline.analyze_post(db, p, terms) for p in new_posts)
    audit.record(
        db,
        "posts.imported",
        request,
        user.id,
        object_type="account",
        object_id=account.id,
        details={
            "created": created,
            "duplicates": duplicates,
            "rejected": rejected,
            "findings": findings,
        },
    )
    db.commit()
    return {
        "created": created,
        "duplicates": duplicates,
        "rejected": rejected,
        "findings_created": findings,
    }


@router.get("/findings")
def list_findings(
    status_: str = "new",
    severity: str | None = None,
    kind: str | None = None,
    platform: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(require_roles("reviewer", "admin")),
    db: Session = Depends(get_db),
) -> list[dict]:
    q = (
        select(Finding, Post, Account)
        .join(Post, Post.id == Finding.post_id)
        .join(Account, Account.id == Post.account_id)
        .where(Finding.status == status_)
        .order_by(Finding.score.desc(), Finding.created_at.desc())
        .limit(max(1, min(limit, 200)))
        .offset(max(0, offset))
    )
    if severity:
        q = q.where(Finding.severity == severity)
    if kind:
        q = q.where(Finding.kind == kind)
    if platform:
        q = q.where(Account.platform == platform)
    out = []
    for f, p, a in db.execute(q).all():
        ev = (
            crypto.decrypt_json(f.evidence_enc, f"findings.evidence:{f.id}")
            if f.evidence_enc
            else {}
        )
        out.append(
            {
                "id": str(f.id),
                "kind": f.kind,
                "severity": f.severity,
                "score": float(f.score),
                "status": f.status,
                "reason": crypto.decrypt_text(f.reason_enc, f"findings.reason:{f.id}"),
                "source": ev.get("source"),
                "snippet": ev.get("snippet"),
                "platform": a.platform,
                "username": a.username,
                "post_url": p.url,
                "posted_at": p.posted_at.isoformat() if p.posted_at else None,
                "created_at": f.created_at.isoformat(),
            }
        )
    return out
