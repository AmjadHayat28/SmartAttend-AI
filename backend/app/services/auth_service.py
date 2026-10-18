"""Authentication use-cases: login, refresh, student self-registration, password change."""

import logging
from datetime import UTC, datetime

from fastapi import HTTPException, Request, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth.dependencies import load_user
from backend.app.auth.rate_limit import get_login_rate_limiter
from backend.app.auth.security import (
    DUMMY_PASSWORD_HASH,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from backend.app.core.config import settings
from backend.app.models import (
    AccountStatus,
    Batch,
    Department,
    Section,
    Semester,
    Student,
    User,
    UserRole,
)
from backend.app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    StudentRegisterRequest,
    TokenResponse,
    UserProfile,
)
from backend.app.services.audit_service import client_ip, record_audit

log = logging.getLogger("smartclass.auth")

_STATUS_MESSAGES = {
    AccountStatus.PENDING: "Your account is awaiting approval.",
    AccountStatus.SUSPENDED: "Your account has been suspended. Contact the administrator.",
    AccountStatus.REJECTED: "Your registration was rejected. Contact your department.",
}


def build_profile(db: Session, user: User) -> UserProfile:
    profile = UserProfile.model_validate(user)
    if user.department_id is not None:
        profile.department_name = db.scalar(
            select(Department.name).where(Department.id == user.department_id)
        )
    if user.hod_profile:
        profile.employee_id = user.hod_profile.employee_id
    elif user.teacher_profile:
        profile.employee_id = user.teacher_profile.employee_id
    elif user.student_profile:
        profile.registration_no = user.student_profile.registration_no
    return profile


def issue_tokens(db: Session, user: User) -> TokenResponse:
    common = {
        "user_id": user.id,
        "role": user.role.value,
        "department_id": user.department_id,
        "token_version": user.token_version,
    }
    return TokenResponse(
        access_token=create_token(**common, token_type="access"),
        refresh_token=create_token(**common, token_type="refresh"),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=build_profile(db, user),
    )


def login(db: Session, data: LoginRequest, request: Request) -> TokenResponse:
    email = data.email.lower()
    limiter_key = f"{client_ip(request)}:{email}"
    limiter = get_login_rate_limiter()
    retry_after = limiter.retry_after(limiter_key, db)
    if retry_after:
        log.warning("login blocked by rate limit: email=%s ip=%s retry_after=%ss", email, client_ip(request), retry_after)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many failed login attempts. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    user_id = db.scalar(select(User.id).where(User.email == email))
    user = load_user(db, user_id) if user_id else None
    password_ok = verify_password(data.password, user.password_hash if user else DUMMY_PASSWORD_HASH)

    if user is None or not password_ok:
        limiter.record_failure(limiter_key, db)
        log.warning("login failed: email=%s ip=%s known_account=%s", email, client_ip(request), user is not None)
        record_audit(db, actor=user, action="auth.login_failed", entity="user",
                     entity_id=user.id if user else None, new_value={"email": email}, request=request)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    limiter.reset(limiter_key, db)
    if user.status != AccountStatus.ACTIVE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _STATUS_MESSAGES[user.status])

    user.last_login_at = datetime.now(UTC)
    record_audit(db, actor=user, action="auth.login", entity="user", entity_id=user.id, request=request)
    db.commit()
    return issue_tokens(db, user)


def refresh(db: Session, refresh_token: str) -> TokenResponse:
    error = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token")
    try:
        payload = decode_token(refresh_token, "refresh")
        user = load_user(db, int(payload["sub"]))
    except (JWTError, KeyError, ValueError):
        raise error from None
    if user is None or user.status != AccountStatus.ACTIVE or payload.get("ver") != user.token_version:
        raise error
    return issue_tokens(db, user)


def register_student(db: Session, data: StudentRegisterRequest, request: Request) -> User:
    email = data.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    if db.scalar(select(Student.id).where(Student.registration_no == data.registration_no)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This registration number is already registered")

    # The chosen batch/semester/section must form a valid chain inside the chosen department.
    section = db.get(Section, data.section_id)
    semester = db.get(Semester, data.semester_id)
    batch = db.get(Batch, data.batch_id)
    department = db.get(Department, data.department_id)
    valid = (
        department is not None and department.is_active
        and batch is not None and batch.department_id == department.id
        and semester is not None and semester.batch_id == batch.id
        and section is not None and section.semester_id == semester.id
    )
    if not valid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid department/batch/semester/section")

    user = User(
        email=email,
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        role=UserRole.STUDENT,
        status=AccountStatus.PENDING,
    )
    user.student_profile = Student(
        department_id=department.id,
        batch_id=batch.id,
        semester_id=semester.id,
        section_id=section.id,
        registration_no=data.registration_no,
    )
    db.add(user)
    db.flush()
    record_audit(db, actor=None, action="student.registered", entity="student",
                 entity_id=user.student_profile.id, department_id=department.id,
                 new_value={"email": email, "registration_no": data.registration_no}, request=request)
    db.commit()
    return user


def issue_onboarding_token(user: User) -> str:
    return create_token(user_id=user.id, role=user.role.value, department_id=user.department_id,
                        token_version=user.token_version, token_type="onboarding")


def onboarding_login(db: Session, data: LoginRequest, request: Request) -> str:
    """Let a *pending* student come back to finish their photos. Same rate limiting and
    anti-enumeration behaviour as login; active students are sent to normal sign-in."""
    email = data.email.lower()
    limiter_key = f"{client_ip(request)}:{email}"
    limiter = get_login_rate_limiter()
    retry_after = limiter.retry_after(limiter_key, db)
    if retry_after:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Too many failed attempts. Try again in {retry_after} seconds.",
                            headers={"Retry-After": str(retry_after)})
    user_id = db.scalar(select(User.id).where(User.email == email))
    user = load_user(db, user_id) if user_id else None
    if user is None or not verify_password(data.password, user.password_hash if user else DUMMY_PASSWORD_HASH):
        limiter.record_failure(limiter_key, db)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    limiter.reset(limiter_key, db)
    if user.role != UserRole.STUDENT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only student registrations use this step")
    if user.status == AccountStatus.ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "Your account is approved. Please sign in normally.")
    if user.status != AccountStatus.PENDING:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _STATUS_MESSAGES[user.status])
    return issue_onboarding_token(user)


def change_password(db: Session, user: User, data: ChangePasswordRequest, request: Request) -> None:
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.password_hash = hash_password(data.new_password)
    user.token_version += 1  # invalidates all existing tokens
    record_audit(db, actor=user, action="auth.password_changed", entity="user", entity_id=user.id, request=request)
    db.commit()
