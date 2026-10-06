"""Run the engines over collected posts and store the results as findings (leads).

Guards, enforced again here even though intake already checks them (defence in depth):
only posts of an OPEN account, under an ACTIVE and in-date consent, that have not expired.
"""

import hashlib
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import media
from ..models import Account, Consent, Finding, Post, WatchlistTerm
from ..security import crypto
from . import image as img_engine
from .text import Hit, TermSpec, analyze_text

ENGINE_VERSION = "rules-1"


def eligible(
    account: Account,
    consent: Consent | None,
    post: Post | None = None,
    today: date | None = None,
) -> str | None:
    """None if monitoring is allowed, else a reason code."""
    today = today or date.today()
    if account.status != "open":
        return "account_not_open"
    if consent is None or consent.status != "active":
        return "no_active_consent"
    if not (consent.valid_from <= today <= consent.valid_until):
        return "consent_not_in_force"
    if post is not None:
        exp = (
            post.delete_after
            if post.delete_after.tzinfo
            else post.delete_after.replace(tzinfo=timezone.utc)
        )
        if exp <= datetime.now(timezone.utc):
            return "post_expired"
    return None


def load_terms(db: Session) -> list[TermSpec]:
    out = []
    for t in db.scalars(
        select(WatchlistTerm).where(WatchlistTerm.active.is_(True))
    ).all():
        ctx = lambda c: f"watchlist_terms.{c}:{t.id}"  # noqa: E731
        aliases = (
            crypto.decrypt_json(t.aliases_enc, ctx("aliases")) if t.aliases_enc else []
        )
        out.append(
            TermSpec(
                str(t.id),
                crypto.decrypt_text(t.term_enc, ctx("term")),
                tuple(aliases),
                t.kind,
                t.severity,
            )
        )
    return out


def post_text(post: Post) -> str:
    return (
        crypto.decrypt_text(post.text_enc, f"posts.text:{post.id}")
        if post.text_enc
        else ""
    )


def _hits_for(
    post: Post, terms: list[TermSpec], clf: img_engine.Classifier
) -> list[Hit]:
    hits = analyze_text(post_text(post), terms, "text")
    for item in post.media or []:
        if item.get("kind") != "image":
            continue
        if item.get("gps"):
            hits.append(img_engine.exif_gps_hit())
        try:
            image = img_engine.load(media.load(item["ref"]))
        except (img_engine.BadImage, FileNotFoundError, crypto.DecryptionError):
            continue
        for h in (
            img_engine.uniform_hit(image),
            *img_engine.classifier_hits(clf, image),
        ):
            if h:
                hits.append(h)
        text = img_engine.ocr_text(image)
        if text:
            hits.extend(analyze_text(text, terms, "ocr"))
    return hits


def analyze_post(
    db: Session,
    post: Post,
    terms: list[TermSpec],
    clf: img_engine.Classifier | None = None,
) -> int:
    """Returns the number of NEW findings. Idempotent: re-running adds nothing."""
    clf = clf or img_engine.NullClassifier()
    account = db.get(Account, post.account_id)
    consent = db.get(Consent, account.consent_id)
    if eligible(account, consent, post) is not None:
        return 0
    new = 0
    created: list[Finding] = []
    for h in _hits_for(post, terms, clf):
        ev_hash = hashlib.sha256(f"{h.source}|{h.key}".encode()).hexdigest()
        if db.scalar(
            select(Finding.id).where(
                Finding.post_id == post.id,
                Finding.kind == h.kind,
                Finding.evidence_hash == ev_hash,
            )
        ):
            continue
        fid = uuid.uuid4()
        finding = Finding(
            id=fid,
            post_id=post.id,
            kind=h.kind,
            score=Decimal(str(h.score)),
            severity=h.severity,
            reason_enc=crypto.encrypt_text(h.reason, f"findings.reason:{fid}"),
            evidence_enc=crypto.encrypt_json(
                {
                    "source": h.source,
                    "snippet": h.snippet,
                    "term_id": h.term_id,
                    "key": h.key,
                    "features": h.features,
                },
                f"findings.evidence:{fid}",
            ),
            evidence_hash=ev_hash,
            engine_version=ENGINE_VERSION,
        )
        db.add(finding)
        created.append(finding)
        new += 1
    post.analyzed_version = ENGINE_VERSION
    db.flush()
    if created:
        from ..learning import (
            service as learning,
        )  # late import: learning reads findings too

        learning.score_findings(db, created)
    return new


def analyze_pending(
    db: Session, limit: int = 200, clf: img_engine.Classifier | None = None
) -> int:
    terms = load_terms(db)
    posts = db.scalars(
        select(Post)
        .where(
            (Post.analyzed_version.is_(None))
            | (Post.analyzed_version != ENGINE_VERSION)
        )
        .limit(limit)
    ).all()
    total = sum(analyze_post(db, p, terms, clf) for p in posts)
    db.commit()
    return total
