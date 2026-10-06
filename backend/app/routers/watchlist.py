from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..deps import require_roles, uuid_or_404
from ..ingest import excel, service
from ..limiter import limiter
from ..models import User, WatchlistTerm
from ..security import crypto
from .imports import _read

router = APIRouter(prefix="/watchlist", tags=["watchlist"])
admin_only = require_roles("admin")


class ActiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool


def _out(t: WatchlistTerm) -> dict:
    ctx = lambda c: f"watchlist_terms.{c}:{t.id}"  # noqa: E731
    return {
        "id": str(t.id),
        "term": crypto.decrypt_text(t.term_enc, ctx("term")),
        "aliases": (
            crypto.decrypt_json(t.aliases_enc, ctx("aliases")) if t.aliases_enc else []
        ),
        "kind": t.kind,
        "severity": t.severity,
        "active": t.active,
    }


@router.get("")
def list_terms(
    user: User = Depends(admin_only), db: Session = Depends(get_db)
) -> list[dict]:
    return [
        _out(t)
        for t in db.scalars(
            select(WatchlistTerm).order_by(WatchlistTerm.created_at)
        ).all()
    ]


@router.post("/import")
@limiter.limit("10/minute")
async def import_terms(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> dict:
    data = await _read(file)
    try:
        terms, rejected = excel.parse_terms(data)
    except excel.FileRejected as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, e.code)
    counts = service.apply_terms(db, terms, user.id)
    audit.record(
        db, "watchlist.imported", request, user.id, details=counts
    )  # counts only, never the terms
    db.commit()
    return {**counts, "rejected": rejected}


class TermIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    term: str = Field(min_length=2, max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    kind: Literal["codename", "site", "unit", "other"] = "codename"
    severity: Literal["low", "medium", "high"] = "medium"


@router.post("", status_code=status.HTTP_201_CREATED)
def add_term(
    body: TermIn,
    request: Request,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> dict:
    term = excel.Term(
        0,
        body.term.strip(),
        [a.strip() for a in body.aliases if a.strip()],
        body.kind,
        body.severity,
    )
    counts = service.apply_terms(db, [term], user.id)
    audit.record(
        db, "watchlist.term_added", request, user.id, details=counts
    )  # counts only, never the term
    db.commit()
    row = db.scalar(
        select(WatchlistTerm).where(
            WatchlistTerm.term_hash == crypto.blind_index(term.term, "watchlist_term")
        )
    )
    return _out(row)


@router.patch("/{term_id}")
def set_active(
    term_id: str,
    body: ActiveIn,
    request: Request,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> dict:
    t = db.get(WatchlistTerm, uuid_or_404(term_id))
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    t.active = body.active
    audit.record(
        db,
        "watchlist.toggled",
        request,
        user.id,
        object_type="watchlist_term",
        object_id=t.id,
        details={"active": body.active},
    )
    db.commit()
    return _out(t)


@router.delete("/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_term(
    term_id: str,
    request: Request,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> None:
    t = db.get(WatchlistTerm, uuid_or_404(term_id))
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    db.delete(t)
    audit.record(
        db,
        "watchlist.deleted",
        request,
        user.id,
        object_type="watchlist_term",
        object_id=term_id,
    )
    db.commit()
