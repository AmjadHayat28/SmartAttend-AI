"""Shared schema building blocks: pagination and normalised input types.

Every identifier is normalised the same way wherever it is accepted, so uniqueness
checks compare like with like (e.g. " f23cse01 " and "F23CSE01" are the same student).
"""

import re
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, BeforeValidator, EmailStr, Field

from backend.app.schemas.auth import validate_password_strength

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


def _collapse_spaces(value: object) -> object:
    return " ".join(value.split()) if isinstance(value, str) else value


def _upper_trim(value: object) -> object:
    return value.strip().upper() if isinstance(value, str) else value


def _code(value: object) -> object:
    """Course codes: trim, upper-case, collapse internal whitespace ("comp  02735" → "COMP 02735")."""
    return re.sub(r"\s+", " ", value.strip().upper()) if isinstance(value, str) else value


Email = Annotated[EmailStr, AfterValidator(lambda v: v.strip().lower())]
FullName = Annotated[str, BeforeValidator(_collapse_spaces), Field(min_length=2, max_length=150)]
Password = Annotated[str, AfterValidator(validate_password_strength)]
EmployeeId = Annotated[
    str,
    BeforeValidator(_upper_trim),
    Field(min_length=2, max_length=50, pattern=r"^[A-Z0-9][A-Z0-9\-_/]*$",
          description="Letters, digits, '-', '_' or '/'"),
]
RegistrationNo = Annotated[
    str, BeforeValidator(_upper_trim), Field(min_length=3, max_length=50, pattern=r"^[A-Z0-9\-/]+$")
]
CourseCode = Annotated[
    str, BeforeValidator(_code), Field(min_length=2, max_length=20, pattern=r"^[A-Z0-9][A-Z0-9 \-_/.]*$")
]
BatchName = Annotated[str, BeforeValidator(_collapse_spaces), Field(min_length=2, max_length=50)]
SectionName = Annotated[
    str, BeforeValidator(_upper_trim), Field(min_length=1, max_length=20, pattern=r"^[A-Z0-9][A-Z0-9\-]*$")
]
Phone = Annotated[
    str, BeforeValidator(lambda v: v.strip() if isinstance(v, str) else v),
    Field(max_length=30, pattern=r"^[0-9+\-() ]*$"),
]
Title = Annotated[str, BeforeValidator(_collapse_spaces), Field(min_length=2, max_length=200)]


class PasswordReset(BaseModel):
    new_password: Password
