import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app

from .conftest import KEY, KEY2

GOOD = dict(
    jwt_secret="j" * 40,
    field_encryption_key=KEY,
    blind_index_key=KEY2,
    retention_days=90,
)


def settings(**over):
    return Settings(_env_file=None, **{**GOOD, **over})


def test_valid_secrets_pass():
    settings().validate_secrets()


@pytest.mark.parametrize(
    "over,message",
    [
        ({"jwt_secret": "short"}, "JWT_SECRET"),
        ({"jwt_secret": ""}, "JWT_SECRET"),
        ({"field_encryption_key": ""}, "FIELD_ENCRYPTION_KEY"),
        ({"field_encryption_key": "not-base64!!"}, "FIELD_ENCRYPTION_KEY"),
        ({"field_encryption_key": "YWJj"}, "FIELD_ENCRYPTION_KEY"),  # 3 bytes
        ({"blind_index_key": ""}, "BLIND_INDEX_KEY"),
        ({"blind_index_key": KEY}, "must differ"),
        ({"retention_days": 0}, "RETENTION_DAYS"),
        ({"retention_days": 99999}, "RETENTION_DAYS"),
    ],
)
def test_weak_or_missing_secrets_are_refused(over, message):
    with pytest.raises(RuntimeError, match=message):
        settings(**over).validate_secrets()


def test_app_refuses_to_start_without_secrets(monkeypatch):
    from app import main

    monkeypatch.setattr(main, "settings", settings(jwt_secret=""))
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        with TestClient(app):
            pass


def test_health_and_docs_disabled(monkeypatch):
    from app import main

    monkeypatch.setattr(main, "settings", settings())
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
