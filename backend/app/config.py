import base64
import binascii

from pydantic_settings import BaseSettings, SettingsConfigDict


def _key_ok(value: str) -> bool:
    try:
        return len(base64.b64decode(value, validate=True)) == 32
    except (binascii.Error, ValueError):
        return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./dev.db"
    environment: str = "development"  # development | test | production

    # Secrets: no defaults on purpose. validate_secrets() runs at startup, not at import,
    # so `alembic` does not need them.
    field_encryption_key: str = (
        ""  # base64 of 32 bytes (AES-256-GCM, encrypted columns)
    )
    blind_index_key: str = (
        ""  # base64 of 32 bytes (HMAC for lookups of encrypted values)
    )
    jwt_secret: str = ""

    # Key ring: ciphertext carries the id of the key that produced it, so keys can be rotated.
    # FIELD_ENCRYPTION_KEY is the current key (id below); older keys stay readable via
    # FIELD_ENCRYPTION_OLD_KEYS="3:<base64>,2:<base64>".
    field_encryption_key_id: int = 1
    field_encryption_old_keys: str = ""

    # Encrypted media files and (optional) trained model weights live outside the database/repo.
    media_dir: str = "/data/media"
    model_dir: str = ""

    # Learning: a model is only trained with at least this many reviewed findings, and only
    # promoted after this many different people approved it.
    learning_min_labels: int = 40
    learning_required_approvals: int = 2

    # Collected public content is deleted automatically after this many days.
    retention_days: int = 90

    # Sessions. Every login creates a "device" (web browser or Android app) that can be revoked.
    access_token_minutes: int = 10
    mfa_token_minutes: int = 5
    setup_token_minutes: int = 15
    session_max_hours_web: int = (
        12  # absolute lifetime; the user must sign in again after this
    )
    session_max_hours_native: int = 168  # 7 days for the Android app
    invite_hours: int = 72
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    totp_issuer: str = "OPSEC Monitor"
    # Refresh cookie path. Use /api/auth when a proxy serves the API under /api.
    refresh_cookie_path: str = "/auth"
    allowed_origins: str = ""  # exact web origins for CORS (empty = same-origin only)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def cookie_secure(self) -> bool:
        return self.environment not in ("development", "test")

    def old_keys(self) -> dict[int, bytes]:
        keys: dict[int, bytes] = {}
        for part in filter(
            None, (p.strip() for p in self.field_encryption_old_keys.split(","))
        ):
            kid, _, b64 = part.partition(":")
            keys[int(kid)] = base64.b64decode(b64, validate=True)
        return keys

    def validate_secrets(self) -> None:
        if len(self.jwt_secret) < 32:
            raise RuntimeError("JWT_SECRET must be set and at least 32 characters")
        if not _key_ok(self.field_encryption_key):
            raise RuntimeError(
                "FIELD_ENCRYPTION_KEY must be base64 of exactly 32 bytes"
            )
        if not _key_ok(self.blind_index_key):
            raise RuntimeError("BLIND_INDEX_KEY must be base64 of exactly 32 bytes")
        if not 1 <= self.field_encryption_key_id <= 255:
            raise RuntimeError("FIELD_ENCRYPTION_KEY_ID must be between 1 and 255")
        try:
            old = self.old_keys()
        except (ValueError, binascii.Error):
            raise RuntimeError(
                "FIELD_ENCRYPTION_OLD_KEYS must look like 'id:base64,id:base64'"
            )
        if (
            any(len(k) != 32 for k in old.values())
            or self.field_encryption_key_id in old
        ):
            raise RuntimeError(
                "FIELD_ENCRYPTION_OLD_KEYS must hold 32-byte keys with ids different from the current one"
            )
        if self.field_encryption_key == self.blind_index_key:
            raise RuntimeError("FIELD_ENCRYPTION_KEY and BLIND_INDEX_KEY must differ")
        if not 1 <= self.retention_days <= 3650:
            raise RuntimeError("RETENTION_DAYS must be between 1 and 3650")


settings = Settings()
