import uuid
from datetime import datetime, timezone
from typing import Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import Device, User
from .security.tokens import Claims, decode_token

_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _claims(creds: HTTPAuthorizationCredentials | None, scope: str) -> Claims:
    if creds is None:
        raise _unauthorized()
    try:
        return decode_token(creds.credentials, scope)
    except (jwt.PyJWTError, ValueError):
        raise _unauthorized()


def step_user(scope: str) -> Callable[..., tuple[User, Claims]]:
    """Login steps (mfa / setup): the user plus the claims carried from the password step."""

    def dependency(
        creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
        db: Session = Depends(get_db),
    ) -> tuple[User, Claims]:
        claims = _claims(creds, scope)
        user = db.get(User, claims.user_id)
        if user is None or not user.is_active:
            raise _unauthorized()
        return user, claims

    return dependency


mfa_pending = step_user("mfa")
setup_pending = step_user("setup")


class Session_:
    """A fully authenticated request: the user and the device the token belongs to."""

    def __init__(self, user: User, device: Device):
        self.user, self.device = user, device


def current_session(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Session_:
    claims = _claims(creds, "access")
    user = db.get(User, claims.user_id)
    device = db.get(Device, claims.device_id) if claims.device_id else None
    # A revoked device loses access immediately, not when its token expires.
    if (
        user is None
        or not user.is_active
        or device is None
        or device.user_id != user.id
        or device.revoked_at is not None
    ):
        raise _unauthorized()
    device.last_seen_at = datetime.now(timezone.utc)
    device.last_ip = request.client.host if request.client else None
    db.commit()
    return Session_(user, device)


def current_user(session: Session_ = Depends(current_session)) -> User:
    return session.user


def require_roles(*roles: str) -> Callable[..., User]:
    """Allow only the listed roles. Everything else gets 403 (and the attempt is not silent)."""

    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    return dependency


def uuid_or_404(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
