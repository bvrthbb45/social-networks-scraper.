"""Password hashing for operator accounts (Argon2id)."""

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

# Explicit parameters (OWASP "second choice" profile: 64 MiB, 3 passes) so a library default
# change can never silently weaken stored hashes.
_ARGON = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
# A well-formed hash of a throw-away value: checked when the account does not exist, so that
# "unknown e-mail" and "wrong password" cost the same time.
_DECOY = _ARGON.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return _ARGON.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """False for a wrong password AND for a hash that is not a valid Argon2 hash
    (e.g. the unusable "!" placed on accounts that have not accepted an invitation yet).
    """
    try:
        return _ARGON.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _ARGON.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def burn_verification_time(password: str) -> None:
    verify_password(_DECOY, password)
