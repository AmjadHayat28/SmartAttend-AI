import re

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from backend.app.core.config import settings
from backend.app.models import AccountStatus, UserRole
from backend.app.schemas.types import UTCDateTime

_REG_NO_PATTERN = re.compile(r"^[A-Za-z0-9\-/]{3,50}$")


def validate_password_strength(value: str) -> str:
    if len(value) < settings.PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters")
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes")
    checks = [r"[a-z]", r"[A-Z]", r"\d"]
    if not all(re.search(pattern, value) for pattern in checks):
        raise ValueError("Password must contain upper-case, lower-case and a digit")
    return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    # Normally empty: the browser sends the refresh token as an HttpOnly cookie. A token in the body
    # is accepted once, to move sessions created before the cookie existed onto the cookie.
    refresh_token: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    _check = field_validator("new_password")(validate_password_strength)


class StudentRegisterRequest(BaseModel):
    """Account details. Profile + face photos are uploaded in Phase 4 (multipart)."""

    full_name: str = Field(min_length=2, max_length=150)
    registration_no: str
    email: EmailStr
    password: str
    department_id: int
    batch_id: int
    semester_id: int
    section_id: int

    _check_password = field_validator("password")(validate_password_strength)

    @field_validator("registration_no")
    @classmethod
    def check_reg_no(cls, value: str) -> str:
        value = value.strip().upper()
        if not _REG_NO_PATTERN.match(value):
            raise ValueError("Registration number may contain letters, digits, '-' and '/' only")
        return value

    @field_validator("full_name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return " ".join(value.split())


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    role: UserRole
    status: AccountStatus
    department_id: int | None
    department_name: str | None = None
    last_login_at: UTCDateTime | None = None
    # Role-specific identifiers
    employee_id: str | None = None
    registration_no: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    # Always null in API responses: the refresh token is only ever sent as an HttpOnly cookie.
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int
    user: UserProfile


class MessageResponse(BaseModel):
    message: str


class OnboardingTokenResponse(BaseModel):
    """Short-lived token that only works on the student's own enrollment-photo endpoints."""

    message: str
    onboarding_token: str
    expires_in: int
