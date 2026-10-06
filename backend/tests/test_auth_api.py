import itertools
from datetime import timedelta

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models as m
from app.config import settings
from app.database import Base, get_db
from app.limiter import limiter
from app.main import app
from app.routers.auth import _now
from tests.conftest import KEY, KEY2

PW = "correct horse battery 7"
_ips = itertools.count(1)


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "j" * 40)
    monkeypatch.setattr(settings, "field_encryption_key", KEY)
    monkeypatch.setattr(settings, "blind_index_key", KEY2)
    limiter.enabled = False
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False)

    def _db():
        with maker() as s:
            yield s

    app.dependency_overrides[get_db] = _db
    yield maker
    app.dependency_overrides.clear()
    limiter.enabled = True


@pytest.fixture()
def api(env):
    return TestClient(app, base_url="https://testserver")


@pytest.fixture()
def db(env):
    with env() as s:
        yield s


def make_user(db, email="a@example.org", role="admin"):
    from app.security.passwords import hash_password

    u = m.User(
        email=email, role=role, password_hash=hash_password(PW), display_name="x"
    )
    db.add(u)
    db.commit()
    return u


def enrol(api, email, client="web", name="dev"):
    """Full first login: password -> 2FA setup -> enable. Returns (session json, secret)."""
    step = api.post(
        "/auth/login",
        json={"email": email, "password": PW, "client": client, "device_name": name},
    ).json()
    assert step["status"] == "2fa_setup_required"
    h = {"Authorization": f"Bearer {step['token']}"}
    secret = api.post("/auth/2fa/setup", headers=h).json()["secret"]
    r = api.post("/auth/2fa/enable", headers=h, json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text
    return r.json(), secret


def login(api, email, secret, client="web", name="dev", step_offset=1):
    step = api.post(
        "/auth/login",
        json={"email": email, "password": PW, "client": client, "device_name": name},
    ).json()
    assert step["status"] == "mfa_required"
    code = pyotp.TOTP(secret).at(_now() + timedelta(seconds=30 * step_offset))
    r = api.post(
        "/auth/2fa/verify",
        headers={"Authorization": f"Bearer {step['token']}"},
        json={"code": code},
    )
    return r


def auth(session):
    return {"Authorization": f"Bearer {session['access_token']}"}


# --- login / 2FA ------------------------------------------------------------- #


def test_full_flow_and_me(api, db):
    make_user(db)
    s, secret = enrol(api, "a@example.org")
    assert len(s["recovery_codes"]) == 10 and s["refresh_token"] is None
    me = api.get("/auth/me", headers=auth(s)).json()
    assert me["role"] == "admin" and me["totp_enabled"] and me["last_login_at"]


def test_wrong_password_unknown_user_same_answer(api, db):
    make_user(db)
    a = api.post(
        "/auth/login", json={"email": "a@example.org", "password": "nope-nope-nope"}
    )
    b = api.post(
        "/auth/login", json={"email": "z@example.org", "password": "nope-nope-nope"}
    )
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_lockout_after_failures(api, db):
    make_user(db)
    for _ in range(settings.max_failed_logins):
        api.post(
            "/auth/login",
            json={"email": "a@example.org", "password": "bad-bad-bad-bad"},
        )
    r = api.post("/auth/login", json={"email": "a@example.org", "password": PW})
    assert r.status_code == 401  # even the right password is refused while locked
    assert db.scalar(select(m.AuditLog).where(m.AuditLog.action == "account.locked"))


def test_access_requires_full_session_not_step_token(api, db):
    make_user(db)
    step = api.post(
        "/auth/login", json={"email": "a@example.org", "password": PW}
    ).json()
    r = api.get("/auth/me", headers={"Authorization": f"Bearer {step['token']}"})
    assert r.status_code == 401


def test_totp_replay_rejected(api, db):
    make_user(db)
    _, secret = enrol(api, "a@example.org")
    ok = login(api, "a@example.org", secret, step_offset=1)
    assert ok.status_code == 200
    again = login(api, "a@example.org", secret, step_offset=1)  # same time step reused
    assert again.status_code == 401


def test_recovery_code_single_use(api, db):
    make_user(db)
    s, _ = enrol(api, "a@example.org")
    code = s["recovery_codes"][0]

    def use():
        step = api.post(
            "/auth/login", json={"email": "a@example.org", "password": PW}
        ).json()
        return api.post(
            "/auth/2fa/verify",
            headers={"Authorization": f"Bearer {step['token']}"},
            json={"recovery_code": code},
        )

    assert use().status_code == 200
    assert use().status_code == 401


# --- devices / sessions ------------------------------------------------------ #


def test_native_client_gets_refresh_in_body_and_rotates(api, db):
    make_user(db)
    s, _ = enrol(api, "a@example.org", client="android", name="Pixel")
    assert s["refresh_token"]
    r1 = api.post("/auth/refresh", json={"refresh_token": s["refresh_token"]})
    assert r1.status_code == 200 and r1.json()["refresh_token"] != s["refresh_token"]
    # replaying the OLD token = theft: the whole device session dies, including the new token
    assert (
        api.post(
            "/auth/refresh", json={"refresh_token": s["refresh_token"]}
        ).status_code
        == 401
    )
    assert (
        api.post(
            "/auth/refresh", json={"refresh_token": r1.json()["refresh_token"]}
        ).status_code
        == 401
    )
    assert api.get("/auth/me", headers=auth(r1.json())).status_code == 401


def test_web_refresh_uses_httponly_cookie(api, db):
    make_user(db)
    enrol(api, "a@example.org")
    cookie = api.cookies.get("refresh_token")
    assert cookie
    assert api.post("/auth/refresh").status_code == 200


def test_revoking_device_blocks_access_immediately(api, db):
    make_user(db)
    s, secret = enrol(api, "a@example.org", client="android")
    other = login(api, "a@example.org", secret, client="web", step_offset=1).json()
    devs = api.get("/auth/devices", headers=auth(other)).json()
    target = next(d for d in devs if not d["current"])["id"]
    assert api.delete(f"/auth/devices/{target}", headers=auth(other)).status_code == 204
    assert api.get("/auth/me", headers=auth(s)).status_code == 401  # revoked
    assert api.get("/auth/me", headers=auth(other)).status_code == 200


def test_cannot_revoke_someone_elses_device(api, db):
    make_user(db)
    make_user(db, "b@example.org", "reviewer")
    a, _ = enrol(api, "a@example.org")
    b, _ = enrol(api, "b@example.org")
    mine = api.get("/auth/devices", headers=auth(a)).json()[0]["id"]
    assert api.delete(f"/auth/devices/{mine}", headers=auth(b)).status_code == 404


def test_absolute_session_lifetime(api, db):
    make_user(db)
    s, _ = enrol(api, "a@example.org", client="android")
    row = db.scalar(select(m.RefreshToken).where(m.RefreshToken.revoked_at.is_(None)))
    row.expires_at = _now() - timedelta(seconds=1)
    db.commit()
    assert (
        api.post(
            "/auth/refresh", json={"refresh_token": s["refresh_token"]}
        ).status_code
        == 401
    )


def test_logout_revokes_device(api, db):
    make_user(db)
    s, _ = enrol(api, "a@example.org")
    assert api.post("/auth/logout", headers=auth(s)).status_code == 204
    assert api.get("/auth/me", headers=auth(s)).status_code == 401


# --- users / RBAC ------------------------------------------------------------ #

ROLE_MATRIX = [  # (method, path, roles allowed)
    ("get", "/users", {"admin"}),
    ("get", "/audit", {"admin", "auditor"}),
]


@pytest.mark.parametrize("role", m.ROLES)
@pytest.mark.parametrize("method,path,allowed", ROLE_MATRIX)
def test_rbac_matrix(api, db, role, method, path, allowed):
    email = f"{role}@example.org"
    make_user(db, email, role)
    s, _ = enrol(api, email)
    r = getattr(api, method)(path, headers=auth(s))
    assert (r.status_code == 200) == (role in allowed), (role, path, r.status_code)
    if role not in allowed:
        assert r.status_code == 403


def test_endpoints_require_authentication(api):
    for path in ("/users", "/audit", "/auth/me", "/auth/devices"):
        assert api.get(path).status_code == 401


def invite(api, admin_session, email="new@example.org", role="reviewer"):
    r = api.post(
        "/users", headers=auth(admin_session), json={"email": email, "role": role}
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_invite_flow_and_single_use(api, db):
    make_user(db)
    a, _ = enrol(api, "a@example.org")
    inv = invite(api, a)
    # stored hashed, never raw
    assert not db.scalar(select(m.Invite).where(m.Invite.token_hash == inv["token"]))
    # cannot log in before accepting (unusable password)
    assert (
        api.post(
            "/auth/login", json={"email": "new@example.org", "password": PW}
        ).status_code
        == 401
    )
    weak = api.post(
        "/auth/accept-invite", json={"token": inv["token"], "password": "short"}
    )
    assert weak.status_code == 422
    ok = api.post("/auth/accept-invite", json={"token": inv["token"], "password": PW})
    assert ok.status_code == 200 and ok.json()["status"] == "2fa_setup_required"
    reuse = api.post(
        "/auth/accept-invite", json={"token": inv["token"], "password": PW}
    )
    assert reuse.status_code == 400


def test_expired_invite_rejected(api, db):
    make_user(db)
    a, _ = enrol(api, "a@example.org")
    inv = invite(api, a)
    row = db.scalar(select(m.Invite))
    row.expires_at = _now() - timedelta(hours=1)
    db.commit()
    r = api.post("/auth/accept-invite", json={"token": inv["token"], "password": PW})
    assert r.status_code == 400


def test_duplicate_user_and_bad_role(api, db):
    make_user(db)
    a, _ = enrol(api, "a@example.org")
    assert (
        api.post(
            "/users", headers=auth(a), json={"email": "A@example.org", "role": "admin"}
        ).status_code
        == 409
    )
    assert (
        api.post(
            "/users", headers=auth(a), json={"email": "x@example.org", "role": "root"}
        ).status_code
        == 422
    )


def test_last_admin_and_self_demotion_guards(api, db):
    u = make_user(db)
    a, _ = enrol(api, "a@example.org")
    r = api.patch(f"/users/{u.id}", headers=auth(a), json={"role": "reviewer"})
    assert r.status_code == 409
    r = api.patch(f"/users/{u.id}", headers=auth(a), json={"is_active": False})
    assert r.status_code == 409
    # with a second admin, demoting the other is fine but self-demotion still is not
    b = make_user(db, "b@example.org", "admin")
    assert (
        api.patch(
            f"/users/{u.id}", headers=auth(a), json={"role": "auditor"}
        ).status_code
        == 409
    )
    assert (
        api.patch(
            f"/users/{b.id}", headers=auth(a), json={"role": "auditor"}
        ).status_code
        == 200
    )


def test_deactivation_kills_sessions_immediately(api, db):
    make_user(db)
    r = make_user(db, "r@example.org", "reviewer")
    a, _ = enrol(api, "a@example.org")
    rs, _ = enrol(api, "r@example.org")
    assert (
        api.patch(
            f"/users/{r.id}", headers=auth(a), json={"is_active": False}
        ).status_code
        == 200
    )
    assert api.get("/auth/me", headers=auth(rs)).status_code == 401
    db.expire_all()
    devices = db.scalars(select(m.Device).where(m.Device.user_id == r.id)).all()
    assert devices and all(d.revoked_at is not None for d in devices)
    tokens = db.scalars(select(m.RefreshToken)).all()
    assert tokens and all(
        t.revoked_at is not None
        for t in tokens
        if t.device_id in {d.id for d in devices}
    )


def test_reset_credentials(api, db):
    make_user(db)
    r = make_user(db, "r@example.org", "reviewer")
    a, _ = enrol(api, "a@example.org")
    rs, secret = enrol(api, "r@example.org")
    res = api.post(f"/users/{r.id}/reset-credentials", headers=auth(a))
    assert res.status_code == 200 and res.json()["purpose"] == "reset"
    assert api.get("/auth/me", headers=auth(rs)).status_code == 401  # devices revoked
    assert (
        api.post(
            "/auth/login", json={"email": "r@example.org", "password": PW}
        ).status_code
        == 401
    )
    api.post("/auth/accept-invite", json={"token": res.json()["token"], "password": PW})
    db.expire_all()
    assert db.get(m.User, r.id).totp_enabled is False  # must enrol 2FA again


def test_audit_trail_records_admin_actions_without_secrets(api, db):
    make_user(db)
    a, _ = enrol(api, "a@example.org")
    inv = invite(api, a)
    rows = api.get("/audit", headers=auth(a)).json()
    actions = {r["action"] for r in rows}
    assert {"login.success", "user.created", "2fa.enabled"} <= actions
    blob = str(rows)
    assert inv["token"] not in blob and PW not in blob


def test_security_headers_and_hidden_openapi(api):
    r = api.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert api.get("/openapi.json").status_code == 404
    assert api.get("/docs").status_code == 404
