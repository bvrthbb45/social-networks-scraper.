"""Retention and housekeeping: nothing collected is kept past its ``delete_after`` date.

Run daily (``python -m app.cli daily``). Every step is idempotent and safe to repeat.
Routine expiry does not retire learning models (see docs/retention-and-reports.md); erasure of
reviewed data on consent revocation does (see ``maintenance.end_consent``).
"""

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import audit, media
from .config import settings
from .models import Device, Finding, Invite, LearningModel, Post, RefreshToken, Review

MIN_ORPHAN_AGE_SECONDS = (
    24 * 3600
)  # never sweep a file an import might still be writing the post for


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _referenced_media(db: Session) -> set[str]:
    refs: set[str] = set()
    for (items,) in db.execute(select(Post.media).where(Post.media.is_not(None))).all():
        refs.update(
            i["ref"] for i in items or [] if isinstance(i, dict) and i.get("ref")
        )
    return refs


def purge_expired_posts(db: Session, now: datetime | None = None) -> dict[str, int]:
    """Delete posts past their retention date. Findings and reviews go with them (database cascade);
    media files go too unless another post still uses the same picture."""
    now = now or _now()
    due = db.execute(select(Post.id, Post.media).where(Post.delete_after <= now)).all()
    if not due:
        return {"posts": 0, "findings": 0, "reviewed_findings": 0, "media_files": 0}
    ids = [pid for pid, _ in due]
    candidate_refs = {
        i["ref"]
        for _, items in due
        for i in (items or [])
        if isinstance(i, dict) and i.get("ref")
    }
    findings = (
        db.scalar(
            select(func.count()).select_from(Finding).where(Finding.post_id.in_(ids))
        )
        or 0
    )
    reviewed = (
        db.scalar(
            select(func.count(func.distinct(Review.finding_id)))
            .join(Finding, Finding.id == Review.finding_id)
            .where(Finding.post_id.in_(ids))
        )
        or 0
    )
    db.execute(delete(Post).where(Post.id.in_(ids)))
    db.flush()
    still_used = _referenced_media(db)
    removed = 0
    for ref in candidate_refs - still_used:
        media.delete(ref)
        removed += 1
    return {
        "posts": len(ids),
        "findings": findings,
        "reviewed_findings": reviewed,
        "media_files": removed,
    }


def sweep_orphan_media(db: Session) -> int:
    """Remove encrypted files that no post refers to (e.g. an import that failed half way)."""
    root = Path(settings.media_dir)
    if not root.is_dir():
        return 0
    used = _referenced_media(db)
    cutoff = time.time() - MIN_ORPHAN_AGE_SECONDS
    removed = 0
    for path in root.glob("??/*.bin"):
        ref = path.stem
        if ref not in used and path.stat().st_mtime < cutoff:
            os.unlink(path)
            removed += 1
    return removed


def cleanup_sessions(db: Session, now: datetime | None = None) -> dict[str, int]:
    """Drop sign-in artefacts that are long dead: used-up refresh tokens, spent invitations, old revoked devices."""
    now = now or _now()
    token_cut = now - timedelta(days=settings.token_cleanup_days)
    device_cut = now - timedelta(days=settings.device_cleanup_days)
    tokens = db.execute(
        delete(RefreshToken).where(
            (RefreshToken.expires_at < token_cut)
            | (RefreshToken.revoked_at < token_cut)
        )
    ).rowcount
    invites = db.execute(
        delete(Invite).where(
            (Invite.expires_at < token_cut) | (Invite.used_at < token_cut)
        )
    ).rowcount
    devices = db.execute(delete(Device).where(Device.revoked_at < device_cut)).rowcount
    return {
        "refresh_tokens": tokens or 0,
        "invites": invites or 0,
        "devices": devices or 0,
    }


def retire_stale_models(db: Session, now: datetime | None = None) -> int:
    limit = settings.learning_max_model_age_days
    if limit <= 0:
        return 0
    now = now or _now()
    n = 0
    for m in db.scalars(
        select(LearningModel).where(LearningModel.status.in_(("active", "shadow")))
    ).all():
        born = (
            m.created_at
            if m.created_at.tzinfo
            else m.created_at.replace(tzinfo=timezone.utc)
        )
        if now - born > timedelta(days=limit):
            m.status, m.retired_at, m.note = "retired", now, "stale"
            n += 1
    if n:
        db.flush()
        from .learning import service as learning

        learning.rescore_open(db)
    return n


def run_daily(db: Session) -> dict:
    """The whole daily routine. Returns the counts that were also written to the audit trail."""
    from .maintenance import expire_consents

    result = {
        "consents_expired": expire_consents(db),  # commits itself
        "purged": purge_expired_posts(db),
        "orphan_media": sweep_orphan_media(db),
        "sessions": cleanup_sessions(db),
        "stale_models": retire_stale_models(db),
    }
    audit.record(
        db, "maintenance.daily", details=_flat(result)
    )  # system action: no user
    db.commit()
    from .analysis.pipeline import analyze_pending

    result["new_findings"] = analyze_pending(db)  # commits itself
    return result


def _flat(d: dict) -> dict:
    out: dict = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update({f"{k}.{kk}": vv for kk, vv in v.items()})
        else:
            out[k] = v
    return out
