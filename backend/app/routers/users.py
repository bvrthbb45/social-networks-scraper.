import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..database import get_db
from ..deps import require_roles, uuid_or_404
from ..models import Invite, User
from ..schemas import InviteOut, UserCreateIn, UserOut, UserPatchIn
from ..security.passwords import hash_password
from ..security.tokens import new_opaque_token
from .auth import revoke_all_devices, user_out

router = APIRouter(prefix="/users", tags=["users"])
admin_only = require_roles("admin")


def _issue_invite(db: Session, user: User, by: User, purpose: str) -> InviteOut:
    raw, hashed = new_opaque_token()
    exp = datetime.now(timezone.utc) + timedelta(hours=settings.invite_hours)
    db.add(
        Invite(
            user_id=user.id,
            purpose=purpose,
            token_hash=hashed,
            expires_at=exp,
            created_by=by.id,
        )
    )
    return InviteOut(
        user_id=str(user.id), token=raw, expires_at=exp.isoformat(), purpose=purpose
    )


def _active_admins(db: Session) -> int:
    return db.scalar(
        select(func.count())
        .select_from(User)
        .where(User.role == "admin", User.is_active.is_(True))
    )


def _get(db: Session, user_id: str) -> User:
    u = db.get(User, uuid_or_404(user_id))
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return u


@router.get("", response_model=list[UserOut])
def list_users(admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    return [
        user_out(u) for u in db.scalars(select(User).order_by(User.created_at)).all()
    ]


@router.post("", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreateIn,
    request: Request,
    admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> InviteOut:
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "User already exists")
    # "!" is not a valid Argon2 hash: the account cannot log in until the invite is accepted.
    user = User(
        email=email, display_name=body.display_name, role=body.role, password_hash="!"
    )
    db.add(user)
    db.flush()
    inv = _issue_invite(db, user, admin, "invite")
    audit.record(
        db,
        "user.created",
        request,
        admin.id,
        object_type="user",
        object_id=user.id,
        details={"role": body.role},
    )
    db.commit()
    return inv


@router.patch("/{user_id}", response_model=UserOut)
def patch_user(
    user_id: str,
    body: UserPatchIn,
    request: Request,
    admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> UserOut:
    user = _get(db, user_id)
    demoting = user.role == "admin" and (
        (body.role is not None and body.role != "admin") or body.is_active is False
    )
    if demoting:
        if user.id == admin.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "You cannot demote or deactivate yourself"
            )
        if user.is_active and _active_admins(db) <= 1:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Cannot remove the last administrator"
            )
    changes: dict = {}
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.role is not None and body.role != user.role:
        changes["role"] = [user.role, body.role]
        user.role = body.role
    if body.is_active is not None and body.is_active != user.is_active:
        changes["is_active"] = body.is_active
        user.is_active = body.is_active
        if not body.is_active:
            revoke_all_devices(db, user.id, admin.id)  # takes effect immediately
    audit.record(
        db,
        "user.updated",
        request,
        admin.id,
        object_type="user",
        object_id=user.id,
        details=changes or None,
    )
    db.commit()
    return user_out(user)


@router.post("/{user_id}/reset-credentials", response_model=InviteOut)
def reset_credentials(
    user_id: str,
    request: Request,
    admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> InviteOut:
    """Lost password/phone: lock the account out, wipe 2FA, hand over a one-time reset link."""
    user = _get(db, user_id)
    user.password_hash = "!"
    user.totp_enabled = False
    user.totp_secret_enc = None
    user.totp_last_step = None
    user.failed_login_count, user.locked_until = 0, None
    revoke_all_devices(db, user.id, admin.id)
    inv = _issue_invite(db, user, admin, "reset")
    audit.record(
        db,
        "user.credentials_reset",
        request,
        admin.id,
        object_type="user",
        object_id=user.id,
    )
    db.commit()
    return inv


_ = (uuid, hash_password)
