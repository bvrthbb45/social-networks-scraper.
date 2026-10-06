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

    # Collected public content is deleted automatically after this many days.
    retention_days: int = 90

    def validate_secrets(self) -> None:
        if len(self.jwt_secret) < 32:
            raise RuntimeError("JWT_SECRET must be set and at least 32 characters")
        if not _key_ok(self.field_encryption_key):
            raise RuntimeError(
                "FIELD_ENCRYPTION_KEY must be base64 of exactly 32 bytes"
            )
        if not _key_ok(self.blind_index_key):
            raise RuntimeError("BLIND_INDEX_KEY must be base64 of exactly 32 bytes")
        if self.field_encryption_key == self.blind_index_key:
            raise RuntimeError("FIELD_ENCRYPTION_KEY and BLIND_INDEX_KEY must differ")
        if not 1 <= self.retention_days <= 3650:
            raise RuntimeError("RETENTION_DAYS must be between 1 and 3650")


settings = Settings()
