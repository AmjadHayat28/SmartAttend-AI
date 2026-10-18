"""Password hashing and JWT helpers.

Hashing uses the `bcrypt` library directly: passlib (unmaintained since 2020) breaks
against bcrypt >= 4.1/5.0. passlib stays installed per the project spec but is not used.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
from jose import JWTError, jwt

from backend.app.core.config import settings

# "onboarding": short-lived, issued at registration so a *pending* student can upload their
# enrollment photos. It is accepted only by the student's own photo endpoints.
TokenType = Literal["access", "refresh", "onboarding"]
_BCRYPT_MAX_BYTES = 72


def _encode_password(password: str) -> bytes:
    # bcrypt only considers the first 72 bytes; reject rather than silently truncate.
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        raise ValueError("Password is too long (max 72 bytes).")
    return raw


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_encode_password(password), bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_encode_password(password), password_hash.encode("utf-8"))
    except ValueError:
        return False


# Used to equalise timing when the email does not exist (prevents user enumeration).
DUMMY_PASSWORD_HASH = hash_password("timing-equaliser-not-a-real-password")


def create_token(
    *,
    user_id: int,
    role: str,
    department_id: int | None,
    token_version: int,
    token_type: TokenType,
) -> str:
    now = datetime.now(UTC)
    if token_type == "access":
        expires = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    elif token_type == "onboarding":
        expires = now + timedelta(minutes=settings.ONBOARDING_TOKEN_EXPIRE_MINUTES)
    else:
        expires = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "dept": department_id,
        "ver": token_version,
        "type": token_type,
        "iat": now,
        "exp": expires,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, expected_type: TokenType | tuple[TokenType, ...]) -> dict[str, Any]:
    """Return the payload or raise JWTError."""
    payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    allowed = (expected_type,) if isinstance(expected_type, str) else expected_type
    if payload.get("type") not in allowed:
        raise JWTError("Wrong token type")
    return payload
