import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..database import get_db
from ..deps import Session_, current_session, mfa_pending, setup_pending
from ..limiter import limiter
from ..models import Device, Invite, RecoveryCode, RefreshToken, User
from ..schemas import (
    AcceptInviteIn,
    DeviceOut,
    LoginIn,
    MfaVerifyIn,
    RefreshIn,
    SessionOut,
    StepTokenOut,
    TotpCodeIn,
    TotpSetupOut,
    UserOut,
    check_password_strength,
)
from ..security import crypto, totp
from ..security.passwords import burn_verification_time, hash_password, verify_password
from ..security.tokens import Claims, create_token, hash_token, new_opaque_token

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
_INVALID = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
_NOT_AUTH = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _totp_context(user: User) -> str:
    return f"users.totp_secret:{user.id}"


def user_out(u: User) -> UserOut:
    return UserOut(
        id=str(u.id),
        email=u.email,
        display_name=u.display_name,
        role=u.role,
        is_active=u.is_active,
        totp_enabled=u.totp_enabled,
        last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
    )


# --- failure accounting ------------------------------------------------------ #


def _locked(user: User) -> bool:
    return user.locked_until is not None and _aware(user.locked_until) > _now()


def _register_failure(db: Session, user: User, request: Request, action: str) -> None:
    user.failed_login_count += 1
    if user.failed_login_count >= settings.max_failed_logins:
        user.locked_until = _now() + timedelta(minutes=settings.lockout_minutes)
        user.failed_login_count = 0
        audit.record(db, "account.locked", request, user.id)
    audit.record(db, action, request, user.id)
    db.commit()


def _clear_failures(user: User) -> None:
    user.failed_login_count = 0
    user.locked_until = None


# --- sessions ---------------------------------------------------------------- #


def _session_hours(kind: str) -> int:
    return (
        settings.session_max_hours_native
        if kind == "android"
        else settings.session_max_hours_web
    )


def _store_refresh(db: Session, device: Device, expires_at: datetime) -> str:
    raw, hashed = new_opaque_token()
    db.add(RefreshToken(device_id=device.id, token_hash=hashed, expires_at=expires_at))
    return raw


def _session_out(
    user: User,
    device: Device,
    raw_refresh: str,
    response: Response,
    recovery_codes: list[str] | None = None,
) -> SessionOut:
    out = SessionOut(
        access_token=create_token(
            user.id, "access", settings.access_token_minutes, device_id=device.id
        ),
        expires_in=settings.access_token_minutes * 60,
        device_id=str(device.id),
        recovery_codes=recovery_codes,
    )
    if device.kind == "android":
        out.refresh_token = raw_refresh  # stored by the app in the Android Keystore
    else:
        response.set_cookie(
            REFRESH_COOKIE,
            raw_refresh,
            max_age=_session_hours("web") * 3600,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
            path=settings.refresh_cookie_path,
        )
    return out


def _open_session(
    db: Session,
    user: User,
    claims: Claims,
    request: Request,
    response: Response,
    recovery_codes: list[str] | None = None,
) -> SessionOut:
    kind = claims.client if claims.client in ("web", "android") else "web"
    device = Device(
        user_id=user.id,
        kind=kind,
        name=claims.device_name or "",
        last_seen_at=_now(),
        last_ip=request.client.host if request.client else None,
    )
    db.add(device)
    db.flush()
    user.last_login_at = _now()
    raw = _store_refresh(db, device, _now() + timedelta(hours=_session_hours(kind)))
    audit.record(
        db, "login.success", request, user.id, object_type="device", object_id=device.id
    )
    return _session_out(user, device, raw, response, recovery_codes)


def _revoke_device(db: Session, device_id: uuid.UUID, by: uuid.UUID | None) -> None:
    db.execute(
        update(Device)
        .where(Device.id == device_id, Device.revoked_at.is_(None))
        .values(revoked_at=_now(), revoked_by=by)
    )
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.device_id == device_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


def revoke_all_devices(db: Session, user_id: uuid.UUID, by: uuid.UUID | None) -> None:
    for did in db.scalars(
        select(Device.id).where(Device.user_id == user_id, Device.revoked_at.is_(None))
    ).all():
        _revoke_device(db, did, by)


# --- endpoints --------------------------------------------------------------- #


@router.post("/accept-invite", response_model=StepTokenOut)
@limiter.limit("5/minute")
def accept_invite(
    request: Request, body: AcceptInviteIn, db: Session = Depends(get_db)
):
    """First password (or a reset). Single use; the claim is one atomic UPDATE."""
    inv = db.scalar(select(Invite).where(Invite.token_hash == hash_token(body.token)))
    if inv is None or inv.used_at is not None or _aware(inv.expires_at) <= _now():
        burn_verification_time(body.password)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Invalid or expired invitation"
        )
    user = db.get(User, inv.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Invalid or expired invitation"
        )
    try:
        check_password_strength(body.password, user.email)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    claimed = db.execute(
        update(Invite)
        .where(Invite.id == inv.id, Invite.used_at.is_(None))
        .values(used_at=_now())
    )
    if claimed.rowcount != 1:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Invalid or expired invitation"
        )
    user.password_hash = hash_password(body.password)
    _clear_failures(user)
    audit.record(db, f"user.{inv.purpose}_accepted", request, user.id)
    db.commit()
    token = create_token(user.id, "setup", settings.setup_token_minutes, client="web")
    return StepTokenOut(status="2fa_setup_required", token=token)


@router.post("/login", response_model=StepTokenOut)
@limiter.limit("5/minute")
def login(
    request: Request, body: LoginIn, db: Session = Depends(get_db)
) -> StepTokenOut:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.is_active:
        burn_verification_time(body.password)
        audit.record(db, "login.failed", request, details={"reason": "unknown"})
        db.commit()
        raise _INVALID
    if _locked(user):
        burn_verification_time(body.password)
        audit.record(db, "login.blocked_locked", request, user.id)
        db.commit()
        raise _INVALID
    if not verify_password(user.password_hash, body.password):
        _register_failure(db, user, request, "login.failed")
        raise _INVALID
    audit.record(db, "login.password_ok", request, user.id)
    db.commit()
    kw = dict(client=body.client, device_name=body.device_name or None)
    if user.totp_enabled:
        return StepTokenOut(
            status="mfa_required",
            token=create_token(user.id, "mfa", settings.mfa_token_minutes, **kw),
        )
    return StepTokenOut(
        status="2fa_setup_required",
        token=create_token(user.id, "setup", settings.setup_token_minutes, **kw),
    )


@router.post("/2fa/setup", response_model=TotpSetupOut)
@limiter.limit("10/minute")
def totp_setup(
    request: Request, step=Depends(setup_pending), db: Session = Depends(get_db)
) -> TotpSetupOut:
    user, _claims = step
    if user.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "2FA already enabled")
    secret = totp.new_secret()
    user.totp_secret_enc = crypto.encrypt(secret.encode(), _totp_context(user))
    audit.record(db, "2fa.setup_started", request, user.id)
    db.commit()
    return TotpSetupOut(
        secret=secret, otpauth_uri=totp.provisioning_uri(secret, user.email)
    )


@router.post("/2fa/enable", response_model=SessionOut)
@limiter.limit("10/minute")
def totp_enable(
    request: Request,
    response: Response,
    body: TotpCodeIn,
    step=Depends(setup_pending),
    db: Session = Depends(get_db),
) -> SessionOut:
    user, claims = step
    if user.totp_enabled or user.totp_secret_enc is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Start 2FA setup first")
    if _locked(user):
        raise _INVALID
    secret = crypto.decrypt(user.totp_secret_enc, _totp_context(user)).decode()
    last = totp.verify(secret, body.code, user.totp_last_step)
    if last is None:
        _register_failure(db, user, request, "2fa.enable_failed")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid code")
    user.totp_enabled = True
    user.totp_last_step = last
    _clear_failures(user)
    db.execute(
        update(RecoveryCode)
        .where(RecoveryCode.user_id == user.id)
        .values(used_at=_now())
    )
    codes = totp.new_recovery_codes()
    db.add_all(
        RecoveryCode(user_id=user.id, code_hash=totp.hash_recovery_code(c))
        for c in codes
    )
    audit.record(db, "2fa.enabled", request, user.id)
    out = _open_session(db, user, claims, request, response, recovery_codes=codes)
    db.commit()
    return out


@router.post("/2fa/verify", response_model=SessionOut)
@limiter.limit("10/minute")
def totp_verify(
    request: Request,
    response: Response,
    body: MfaVerifyIn,
    step=Depends(mfa_pending),
    db: Session = Depends(get_db),
) -> SessionOut:
    user, claims = step
    if (body.code is None) == (body.recovery_code is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Provide exactly one of code or recovery_code",
        )
    if _locked(user):
        audit.record(db, "2fa.blocked_locked", request, user.id)
        db.commit()
        raise _INVALID
    ok = False
    if body.code is not None and user.totp_secret_enc is not None:
        secret = crypto.decrypt(user.totp_secret_enc, _totp_context(user)).decode()
        last = totp.verify(secret, body.code, user.totp_last_step)
        if last is not None:
            user.totp_last_step = last
            ok = True
    elif body.recovery_code is not None:
        claimed = db.execute(
            update(RecoveryCode)
            .where(
                RecoveryCode.user_id == user.id,
                RecoveryCode.code_hash == totp.hash_recovery_code(body.recovery_code),
                RecoveryCode.used_at.is_(None),
            )
            .values(used_at=_now())
        )
        ok = claimed.rowcount == 1
        if ok:
            audit.record(db, "2fa.recovery_code_used", request, user.id)
    if not ok:
        _register_failure(db, user, request, "2fa.failed")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid code")
    _clear_failures(user)
    out = _open_session(db, user, claims, request, response)
    db.commit()
    return out


@router.post("/refresh", response_model=SessionOut)
@limiter.limit("30/minute")
def refresh(
    request: Request,
    response: Response,
    body: RefreshIn | None = None,
    cookie: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    db: Session = Depends(get_db),
) -> SessionOut:
    presented = (body.refresh_token if body else None) or cookie
    if not presented:
        raise _NOT_AUTH
    row = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(presented))
    )
    if row is None:
        raise _NOT_AUTH
    device = db.get(Device, row.device_id)
    if row.revoked_at is not None:
        # An already-rotated token came back: assume theft and end this device's session.
        if device is not None:
            _revoke_device(db, device.id, None)
            audit.record(
                db,
                "refresh.reuse_detected",
                request,
                device.user_id,
                object_type="device",
                object_id=device.id,
            )
        db.commit()
        response.delete_cookie(REFRESH_COOKIE, path=settings.refresh_cookie_path)
        raise _NOT_AUTH
    user = db.get(User, device.user_id) if device else None
    if (
        device is None
        or device.revoked_at is not None
        or user is None
        or not user.is_active
        or _aware(row.expires_at)
        <= _now()  # absolute lifetime: fixed at login, never extended
    ):
        raise _NOT_AUTH
    row.revoked_at = _now()
    raw = _store_refresh(db, device, row.expires_at)
    out = _session_out(user, device, raw, response)
    db.commit()
    return out


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    session: Session_ = Depends(current_session),
    db: Session = Depends(get_db),
) -> None:
    _revoke_device(db, session.device.id, session.user.id)
    audit.record(
        db,
        "logout",
        request,
        session.user.id,
        object_type="device",
        object_id=session.device.id,
    )
    db.commit()
    response.delete_cookie(REFRESH_COOKIE, path=settings.refresh_cookie_path)


@router.get("/me", response_model=UserOut)
def me(session: Session_ = Depends(current_session)) -> UserOut:
    return user_out(session.user)


@router.get("/devices", response_model=list[DeviceOut])
def my_devices(
    session: Session_ = Depends(current_session), db: Session = Depends(get_db)
) -> list[DeviceOut]:
    rows = db.scalars(
        select(Device)
        .where(Device.user_id == session.user.id)
        .order_by(Device.created_at.desc())
    ).all()
    return [device_out(d, d.id == session.device.id) for d in rows]


def device_out(d: Device, current: bool = False) -> DeviceOut:
    return DeviceOut(
        id=str(d.id),
        kind=d.kind,
        name=d.name,
        created_at=d.created_at.isoformat(),
        last_seen_at=d.last_seen_at.isoformat() if d.last_seen_at else None,
        revoked_at=d.revoked_at.isoformat() if d.revoked_at else None,
        current=current,
    )


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_my_device(
    device_id: str,
    request: Request,
    session: Session_ = Depends(current_session),
    db: Session = Depends(get_db),
) -> None:
    try:
        did = uuid.UUID(device_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    d = db.get(Device, did)
    if (
        d is None or d.user_id != session.user.id
    ):  # other users' devices look nonexistent
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    _revoke_device(db, did, session.user.id)
    audit.record(
        db,
        "device.revoked",
        request,
        session.user.id,
        object_type="device",
        object_id=did,
    )
    db.commit()
