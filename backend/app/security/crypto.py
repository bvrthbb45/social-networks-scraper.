"""Field-level encryption (AES-256-GCM) with a key ring, plus HMAC blind indexes.

Blob layout: 1 byte key id | 12 byte random nonce | ciphertext+tag.
``context`` is authenticated as AAD (e.g. ``"users.totp_secret:<user id>"``), so a
ciphertext copied to another row or column fails to decrypt.

Rotation: set a new FIELD_ENCRYPTION_KEY with a new id, keep the previous key in
FIELD_ENCRYPTION_OLD_KEYS, then run ``rotate()`` over the data. Old blobs stay readable
meanwhile.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import unicodedata

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import settings


class DecryptionError(Exception):
    pass


def _current() -> tuple[int, bytes]:
    return settings.field_encryption_key_id, base64.b64decode(
        settings.field_encryption_key, validate=True
    )


def _key_for(key_id: int) -> bytes:
    cur_id, cur = _current()
    if key_id == cur_id:
        return cur
    try:
        return settings.old_keys()[key_id]
    except KeyError:
        raise DecryptionError(f"unknown key id {key_id}")


def encrypt(plaintext: bytes, context: str) -> bytes:
    key_id, key = _current()
    nonce = os.urandom(12)
    return (
        bytes([key_id])
        + nonce
        + AESGCM(key).encrypt(nonce, plaintext, context.encode())
    )


def decrypt(blob: bytes, context: str) -> bytes:
    if len(blob) < 1 + 12 + 16:
        raise DecryptionError("malformed ciphertext")
    key = _key_for(blob[0])
    try:
        return AESGCM(key).decrypt(blob[1:13], blob[13:], context.encode())
    except InvalidTag as exc:
        raise DecryptionError("authentication failed") from exc


def key_id_of(blob: bytes) -> int:
    return blob[0]


def rotate(blob: bytes, context: str) -> bytes:
    """Re-encrypt under the current key (no-op if already current)."""
    if blob[0] == settings.field_encryption_key_id:
        return blob
    return encrypt(decrypt(blob, context), context)


def encrypt_text(text: str, context: str) -> bytes:
    return encrypt(text.encode(), context)


def decrypt_text(blob: bytes, context: str) -> str:
    return decrypt(blob, context).decode()


def encrypt_json(value, context: str) -> bytes:
    return encrypt(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(), context
    )


def decrypt_json(blob: bytes, context: str):
    return json.loads(decrypt(blob, context))


# --- blind index --------------------------------------------------------------- #

_HEBREW_MARKS = re.compile(r"[֑-ׇ]")  # niqqud and cantillation
_SPACES = re.compile(r"\s+")


def normalize(value: str) -> str:
    """Canonical form for matching: NFKC, no Hebrew points, case-folded, single spaces."""
    text = unicodedata.normalize("NFKC", value)
    text = _HEBREW_MARKS.sub("", text).casefold()
    return _SPACES.sub(" ", text).strip()


def blind_index(value: str, purpose: str) -> str:
    """Deterministic keyed hash: lets us look records up (and enforce uniqueness) without
    decrypting. ``purpose`` separates indexes so equal values in different columns differ.
    """
    key = base64.b64decode(settings.blind_index_key, validate=True)
    return hmac.new(
        key, f"{purpose}:{normalize(value)}".encode(), hashlib.sha256
    ).hexdigest()
