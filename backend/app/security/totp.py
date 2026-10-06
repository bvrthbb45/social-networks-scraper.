import hashlib
import hmac
import secrets
import time

import pyotp

from ..config import settings

STEP = 30
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alike characters


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(
        name=email, issuer_name=settings.totp_issuer
    )


def verify(secret: str, code: str, last_step: int | None) -> int | None:
    """Check a 6-digit code (±1 step of clock drift).

    Returns the matched time step, or None. A step that is not newer than
    ``last_step`` is rejected, so a code cannot be replayed.
    """
    if not (code.isascii() and code.isdigit() and len(code) == 6):
        return None
    now_step = int(time.time()) // STEP
    totp = pyotp.TOTP(secret, interval=STEP)
    for step in (now_step - 1, now_step, now_step + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(totp.at(step * STEP), code):
            return step
    return None


def new_recovery_codes(n: int = 10) -> list[str]:
    def one() -> str:
        return "".join(secrets.choice(_ALPHABET) for _ in range(10))

    return [f"{c[:5]}-{c[5:]}" for c in (one() for _ in range(n))]


def hash_recovery_code(code: str) -> str:
    # Codes are 50 bits of randomness, so a fast hash is sufficient.
    return hashlib.sha256(code.strip().lower().encode()).hexdigest()
