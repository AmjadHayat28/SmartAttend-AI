"""FastAPI dependencies for authentication, role checks and department isolation.

Domain permissions are explicit — the super admin is a *system administrator*, not "allowed
everywhere":
- System/staff administration (departments, HODs, teachers, staff accounts):
  super admin (+ HOD for their own department's teachers).
- Department academics and students (students, approvals, face review, batches/semesters/
  sections/courses, teacher-to-class assignments): HOD only.
- Student course enrollments: the teacher of the class (their own active assignment) only.
- Attendance sessions (taking, recognition, classroom photos, corrections, deletion, history):
  the teacher who teaches the class, only. HODs and the super admin are refused (403).
- Attendance reports and Excel export: the teacher, for their own active classes only
  (HOD / super admin / student: 403).
- Student "My Attendance": the signed-in student's own records only.

Usage in a route:

    @router.get("/x", dependencies=[Depends(require_roles(UserRole.SUPER_ADMIN))])
    def x(user: CurrentUser): ...

    ensure_department_access(user, department_id)    # HOD / teacher / student scope
    ensure_teacher_assignment(db, user, course_id, section_id)
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.app.auth.security import decode_token
from backend.app.database.session import get_db
from backend.app.models import AccountStatus, TeacherCourseAssignment, User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def load_user(db: Session, user_id: int) -> User | None:
    return db.scalar(
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.hod_profile),
            selectinload(User.teacher_profile),
            selectinload(User.student_profile),
        )
    )


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _CREDENTIALS_ERROR
    try:
        payload = decode_token(credentials.credentials, "access")
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise _CREDENTIALS_ERROR from None

    user = load_user(db, user_id)
    # Re-check status on every request so suspensions take effect immediately.
    if user is None or payload.get("ver") != user.token_version:
        raise _CREDENTIALS_ERROR
    if user.status != AccountStatus.ACTIVE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Account is {user.status.value}")
    if user.role != UserRole.SUPER_ADMIN and user.department_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is not linked to a department")
    if user.role == UserRole.HOD and not user.hod_profile.is_current:
        # A replaced HOD keeps their history row but loses all department access.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are no longer the HOD of this department")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    allowed = set(roles)

    def checker(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission for this action")
        return user

    return checker


AdminUser = Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN))]
AdminOrHod = Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.HOD))]
HodUser = Annotated[User, Depends(require_roles(UserRole.HOD))]
TeacherUser = Annotated[User, Depends(require_roles(UserRole.TEACHER))]
StudentUser = Annotated[User, Depends(require_roles(UserRole.STUDENT))]


def scoped_department_id(user: User) -> int | None:
    """Department filter to apply to queries. None means "all departments" (super admin)."""
    if user.role == UserRole.SUPER_ADMIN:
        return None
    if user.department_id is None:
        # A non-admin account without a profile must never fall through to "see everything".
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is not linked to a department")
    return user.department_id


def ensure_department_access(user: User, department_id: int) -> None:
    scope = scoped_department_id(user)
    if scope is not None and scope != department_id:
        # 404 rather than 403 so other departments' resources are not disclosed.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found")


def ensure_teacher_assignment(db: Session, user: User, course_id: int, section_id: int) -> None:
    """Teachers may act only on (course, section) pairs actively assigned to them.
    HODs pass if the course belongs to their department."""
    if user.role == UserRole.TEACHER and user.teacher_profile:
        assigned = db.scalar(
            select(TeacherCourseAssignment.id).where(
                TeacherCourseAssignment.teacher_id == user.teacher_profile.id,
                TeacherCourseAssignment.course_id == course_id,
                TeacherCourseAssignment.section_id == section_id,
                TeacherCourseAssignment.is_active.is_(True),
            )
        )
        if assigned:
            return
    elif user.role == UserRole.HOD:
        dept = db.scalar(
            select(TeacherCourseAssignment.department_id).where(
                TeacherCourseAssignment.course_id == course_id,
                TeacherCourseAssignment.section_id == section_id,
            )
        )
        if dept is not None and dept == user.department_id:
            return
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")


# ── Phase 4: face enrollment ───────────────────────────────────────────────


def _token_user(db: Session, credentials: HTTPAuthorizationCredentials | None) -> tuple[User, str]:
    """Authenticate an access *or* onboarding token. Returns (user, token type)."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _CREDENTIALS_ERROR
    try:
        payload = decode_token(credentials.credentials, ("access", "onboarding"))
        user = load_user(db, int(payload["sub"]))
    except (JWTError, KeyError, ValueError):
        raise _CREDENTIALS_ERROR from None
    if user is None or payload.get("ver") != user.token_version:
        raise _CREDENTIALS_ERROR
    return user, payload["type"]


def get_enrolling_student(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    """The student managing their *own* photos: an active student with a normal access token,
    or a pending student with the onboarding token issued at registration."""
    user, token_type = _token_user(db, credentials)
    if user.role != UserRole.STUDENT or user.student_profile is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only students manage their own enrollment photos")
    allowed = {AccountStatus.ACTIVE} if token_type == "access" else {AccountStatus.PENDING, AccountStatus.ACTIVE}
    if user.status not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Account is {user.status.value}")
    return user


EnrollingStudent = Annotated[User, Depends(get_enrolling_student)]


def get_image_viewer(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    """Anyone allowed to *request* a student image: normal signed-in users, plus the
    onboarding student (for their own photos). Per-image authorisation happens in the service."""
    user, token_type = _token_user(db, credentials)
    if token_type == "onboarding":
        return get_enrolling_student(db, credentials)
    return get_current_user(db, credentials)


ImageViewer = Annotated[User, Depends(get_image_viewer)]
