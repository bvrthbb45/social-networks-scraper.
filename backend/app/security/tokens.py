import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt

from ..config import settings

ISSUER = "opsec-monitor"
AUDIENCE = "opsec-monitor-api"
ALGORITHM = "HS256"

# access: full session | mfa: password ok, TOTP pending | setup: must enrol 2FA
SCOPES = ("access", "mfa", "setup")


@dataclass(frozen=True)
class Claims:
    user_id: uuid.UUID
    device_id: uuid.UUID | None
    client: str | None  # "web" | "android" (step tokens only)
    device_name: str | None


def create_token(
    user_id: uuid.UUID,
    scope: str,
    minutes: int,
    *,
    device_id: uuid.UUID | None = None,
    client: str | None = None,
    device_name: str | None = None,
) -> str:
    assert scope in SCOPES
    now = datetime.now(timezone.utc)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(user_id),
        "scope": scope,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    if device_id:
        claims["did"] = str(device_id)
    if client:
        claims["cl"] = client
    if device_name:
        claims["dn"] = device_name[:120]
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str, scope: str) -> Claims:
    """Return the claims or raise jwt.PyJWTError / ValueError."""
    c = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[ALGORITHM],  # never trust the header's alg
        audience=AUDIENCE,
        issuer=ISSUER,
        options={"require": ["exp", "iat", "sub", "scope"]},
    )
    if c["scope"] != scope:
        raise jwt.InvalidTokenError("wrong scope")
    did = c.get("did")
    return Claims(
        uuid.UUID(c["sub"]), uuid.UUID(did) if did else None, c.get("cl"), c.get("dn")
    )


def new_opaque_token() -> tuple[str, str]:
    """(token handed to the client, sha256 hex stored in the database)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
