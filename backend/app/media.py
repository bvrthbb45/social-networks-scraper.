"""Encrypted media store. Files are AES-256-GCM encrypted at rest and addressed by the SHA-256
of their (metadata-stripped) content, so the same picture is stored once. Nothing here ever
touches the database or the repository; ``media_dir`` is a mounted volume."""

import hashlib
import os
from pathlib import Path

from .config import settings
from .security import crypto


def _path(ref: str) -> Path:
    if len(ref) != 64 or any(c not in "0123456789abcdef" for c in ref):
        raise ValueError("bad media ref")
    return Path(settings.media_dir) / ref[:2] / f"{ref}.bin"


def save(data: bytes) -> str:
    ref = hashlib.sha256(data).hexdigest()
    path = _path(ref)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(crypto.encrypt(data, f"media:{ref}"))
        os.replace(tmp, path)  # atomic: never a half-written file
        path.chmod(0o600)
    return ref


def load(ref: str) -> bytes:
    return crypto.decrypt(_path(ref).read_bytes(), f"media:{ref}")


def delete(ref: str) -> None:
    _path(ref).unlink(missing_ok=True)
