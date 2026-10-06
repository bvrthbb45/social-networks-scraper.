import base64
import uuid

import jwt
import pytest

from app.config import settings
from app.security import crypto, tokens
from tests.conftest import KEY, KEY2


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "j" * 40)
    monkeypatch.setattr(settings, "field_encryption_key", KEY)
    monkeypatch.setattr(settings, "field_encryption_key_id", 1)
    monkeypatch.setattr(settings, "field_encryption_old_keys", "")
    monkeypatch.setattr(settings, "blind_index_key", KEY2)


def test_roundtrip_and_context_binding():
    blob = crypto.encrypt(b"secret", "ctx:1")
    assert b"secret" not in blob and crypto.decrypt(blob, "ctx:1") == b"secret"
    with pytest.raises(Exception):
        crypto.decrypt(blob, "ctx:2")  # ciphertext moved to another field/row


def test_tamper_detected():
    blob = bytearray(crypto.encrypt(b"secret", "c"))
    blob[-1] ^= 1
    with pytest.raises(Exception):
        crypto.decrypt(bytes(blob), "c")


def test_nonce_unique():
    assert crypto.encrypt(b"x", "c") != crypto.encrypt(b"x", "c")


def test_key_rotation_keeps_old_data_readable(monkeypatch):
    old = crypto.encrypt(b"data", "c")
    new_key = base64.b64encode(b"n" * 32).decode()
    monkeypatch.setattr(settings, "field_encryption_old_keys", f"1:{KEY}")
    monkeypatch.setattr(settings, "field_encryption_key", new_key)
    monkeypatch.setattr(settings, "field_encryption_key_id", 2)
    assert crypto.decrypt(old, "c") == b"data"
    rotated = crypto.rotate(old, "c")
    assert crypto.key_id_of(rotated) == 2 and crypto.decrypt(rotated, "c") == b"data"


def test_blind_index_normalises_hebrew_and_is_purpose_bound():
    a = crypto.blind_index("שָׁלוֹם", "name")
    assert a == crypto.blind_index("שלום", "name")
    assert a != crypto.blind_index("שלום", "other")


def test_token_scopes_are_not_interchangeable():
    uid, did = uuid.uuid4(), uuid.uuid4()
    t = tokens.create_token(uid, "access", 5, device_id=did)
    assert tokens.decode_token(t, "access").device_id == did
    for scope in ("mfa", "setup"):
        with pytest.raises(jwt.PyJWTError):
            tokens.decode_token(t, scope)


def test_expired_and_forged_tokens_rejected(monkeypatch):
    uid = uuid.uuid4()
    with pytest.raises(jwt.PyJWTError):
        tokens.decode_token(tokens.create_token(uid, "access", -1), "access")
    forged = jwt.encode(
        {"sub": str(uid), "scope": "access"}, "wrong" * 10, algorithm="HS256"
    )
    with pytest.raises(jwt.PyJWTError):
        tokens.decode_token(forged, "access")
    none_alg = jwt.encode({"sub": str(uid), "scope": "access"}, None, algorithm="none")
    with pytest.raises(jwt.PyJWTError):
        tokens.decode_token(none_alg, "access")
