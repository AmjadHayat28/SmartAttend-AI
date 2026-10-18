"""Department-scope helpers used by every management service.

The rule: a HOD's department always comes from their own profile, never from request
input. Anything outside the caller's department behaves exactly like a missing record (404),
so the existence of other departments' data is never revealed.
"""

from typing import Any, TypeVar

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from backend.app.auth.dependencies import scoped_department_id
from backend.app.models import Department, User
from backend.app.schemas.common import Page

M = TypeVar("M")


def not_found(label: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{label} not found")


def resolve_department_id(db: Session, user: User, requested: int | None) -> int:
    """Department to act in. HODs: always their own (a different requested id → 404).
    Super admin: the requested department, which must exist."""
    scope = scoped_department_id(user)
    if scope is not None:
        if requested is not None and requested != scope:
            raise not_found("Department")
        return scope
    if requested is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "department_id is required")
    if db.get(Department, requested) is None:
        raise not_found("Department")
    return requested


def get_in_scope(db: Session, model: type[M], obj_id: int, user: User, label: str) -> M:
    """Load a department-owned row, or 404 if it is missing or outside the caller's scope."""
    obj = db.get(model, obj_id)
    scope = scoped_department_id(user)
    if obj is None or (scope is not None and obj.department_id != scope):  # type: ignore[attr-defined]
        raise not_found(label)
    return obj


def apply_scope(stmt: Select, column: Any, user: User, requested: int | None = None) -> Select:
    """Filter a list query to the caller's department (and optional requested filter)."""
    scope = scoped_department_id(user)
    if scope is not None:
        if requested is not None and requested != scope:
            return stmt.where(False)  # asking for another department yields nothing
        return stmt.where(column == scope)
    if requested is not None:
        return stmt.where(column == requested)
    return stmt


def paginate(db: Session, stmt: Select, page: int, page_size: int, transform=None) -> Page:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    items = [transform(row) if transform else row[0] for row in rows]
    return Page(items=items, total=total, page=page, page_size=page_size)


def like(q: str) -> str:
    """Case-insensitive LIKE pattern with wildcards escaped."""
    escaped = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
