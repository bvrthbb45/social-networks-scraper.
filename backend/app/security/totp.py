"""Time-based one-time codes (RFC 6238) and single-use recovery codes."""

import hashlib
import hmac
import re
import secrets
import time

import pyotp

from ..config import settings

PERIOD = 30  # seconds per code
DRIFT = 1  # accept codes from one period before / after (clock skew)
RECOVERY_COUNT = 10
# Crockford-style alphabet without characters that are easy to misread (0/o, 1/l/i).
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstvwxyz23456789"


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(
        name=email, issuer_name=settings.totp_issuer
    )


def _steps_around(now: float) -> range:
    current = int(now // PERIOD)
    return range(current - DRIFT, current + DRIFT + 1)


def verify(secret: str, code: str, last_step: int | None) -> int | None:
    """Return the time step the code belongs to, or None.

    ``last_step`` is the newest step already used by this account; any step at or before it is
    refused, so an intercepted code cannot be replayed within its validity window.
    """
    if len(code) != 6 or not (code.isascii() and code.isdigit()):
        return None
    generator = pyotp.TOTP(secret, interval=PERIOD)
    for step in _steps_around(time.time()):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(generator.at(step * PERIOD), code):
            return step
    return None


def new_recovery_codes(n: int = RECOVERY_COUNT) -> list[str]:
    """Codes look like ``abcde-fghjk`` (50 bits each)."""
    codes = []
    for _ in range(n):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def hash_recovery_code(code: str) -> str:
    """Case, spaces and the dash are ignored when comparing. 50 random bits make a plain
    SHA-256 adequate for storage (there is nothing to brute-force offline)."""
    canonical = re.sub(r"[\s-]", "", code).lower()
    return hashlib.sha256(f"recovery:{canonical}".encode()).hexdigest()
