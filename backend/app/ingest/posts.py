"""Intake of already-collected PUBLIC content for an open, consenting account.

This module does not fetch anything from any platform: collection is done by an approved
connector outside this service (or by hand) and delivered through the API.
"""

import base64
import binascii
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import media
from ..analysis import image as img_engine
from ..analysis.pipeline import eligible
from ..config import settings
from ..models import Account, Consent, Post
from ..security import crypto

MAX_TEXT = 20_000
MAX_IMAGES = 5


class Rejected(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def find_account(db: Session, platform: str, username: str) -> tuple[Account, Consent]:
    acct = db.scalar(
        select(Account).where(
            Account.platform == platform,
            Account.username == username.lstrip("@").lower(),
        )
    )
    if acct is None:
        raise Rejected("unknown_account")
    consent = db.get(Consent, acct.consent_id)
    reason = eligible(acct, consent)
    if reason:
        raise Rejected(
            reason
        )  # closed/unknown account, revoked/expired consent: collect nothing
    return acct, consent


def add_post(db: Session, account: Account, item: dict) -> Post | None:
    """Create one post. Returns None for an exact duplicate. Raises Rejected on bad content."""
    text = (item.get("text") or "").strip()
    if len(text) > MAX_TEXT:
        raise Rejected("text_too_long")
    images: list[bytes] = []
    for b64 in (item.get("images") or [])[: MAX_IMAGES + 1]:
        try:
            images.append(base64.b64decode(b64, validate=True))
        except (binascii.Error, ValueError):
            raise Rejected("bad_image_encoding")
    if len(images) > MAX_IMAGES:
        raise Rejected("too_many_images")
    if not text and not images:
        raise Rejected("empty_post")

    entries, digests = [], []
    for raw in images:
        try:
            image = img_engine.load(raw)
        except img_engine.BadImage as e:
            raise Rejected(f"image_{e}")
        gps = img_engine.has_gps(raw)  # read BEFORE the metadata is stripped
        ref = media.save(img_engine.strip_metadata(image))
        entries.append({"kind": "image", "ref": ref, "gps": gps})
        digests.append(hashlib.sha256(raw).hexdigest())
    content_hash = hashlib.sha256(
        ("\x00".join([crypto.normalize(text), *digests])).encode()
    ).hexdigest()
    if db.scalar(
        select(Post.id).where(
            Post.account_id == account.id, Post.content_hash == content_hash
        )
    ):
        return None
    pid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    post = Post(
        id=pid,
        account_id=account.id,
        external_id=(item.get("external_id") or None),
        url=(item.get("url") or None),
        posted_at=item.get("posted_at"),
        text_enc=crypto.encrypt_text(text, f"posts.text:{pid}") if text else None,
        media=entries or None,
        content_hash=content_hash,
        collected_at=now,
        delete_after=now + timedelta(days=settings.retention_days),
    )
    db.add(post)
    db.flush()
    return post
