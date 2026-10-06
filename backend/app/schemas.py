import re

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .models import ROLES

_COMMON = {
    "password",
    "passw0rd",
    "123456789012",
    "qwertyuiop12",
    "letmein12345",
    "administrator1",
    "welcome12345",
    "changeme1234",
    "iloveyou1234",
    "password1234",
    "סיסמה12345",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def check_password_strength(password: str, email: str = "") -> str:
    if len(password) < 12:
        raise ValueError("password too short")
    if password.lower() in _COMMON or len(set(password)) < 5:
        raise ValueError("password too common")
    local = email.split("@")[0].lower()
    if len(local) >= 4 and local in password.lower():
        raise ValueError("password contains the e-mail name")
    return password


class LoginIn(_Strict):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    client: str = Field(default="web", pattern="^(web|android)$")
    device_name: str = Field(default="", max_length=120)


class AcceptInviteIn(_Strict):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=12, max_length=128)


class TotpCodeIn(_Strict):
    code: str = Field(min_length=6, max_length=6)


class MfaVerifyIn(_Strict):
    code: str | None = Field(default=None, min_length=6, max_length=6)
    recovery_code: str | None = Field(default=None, min_length=11, max_length=11)


class RefreshIn(_Strict):
    refresh_token: str | None = Field(default=None, max_length=200)


class StepTokenOut(BaseModel):
    status: str  # "mfa_required" | "2fa_setup_required"
    token: str


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class SessionOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    device_id: str
    recovery_codes: list[str] | None = None
    refresh_token: str | None = (
        None  # native clients only; browsers get an httpOnly cookie
    )


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    is_active: bool
    totp_enabled: bool
    last_login_at: str | None = None


class DeviceOut(BaseModel):
    id: str
    kind: str
    name: str
    created_at: str
    last_seen_at: str | None
    revoked_at: str | None
    current: bool = False


class UserCreateIn(_Strict):
    email: EmailStr
    display_name: str = Field(default="", max_length=120)
    role: str

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in ROLES:
            raise ValueError("unknown role")
        return v


class UserPatchIn(_Strict):
    display_name: str | None = Field(default=None, max_length=120)
    role: str | None = None
    is_active: bool | None = None

    @field_validator("role")
    @classmethod
    def _role(cls, v: str | None) -> str | None:
        if v is not None and v not in ROLES:
            raise ValueError("unknown role")
        return v


class InviteOut(BaseModel):
    user_id: str
    token: str  # shown ONCE; only its hash is stored
    expires_at: str
    purpose: str


class AuditOut(BaseModel):
    id: int
    user_id: str | None
    action: str
    object_type: str | None
    object_id: str | None
    ip: str | None
    details: dict | None
    created_at: str


_ = re  # silence linters if unused
