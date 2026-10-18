"""Role-specific dashboard summaries (counts only; analytics arrive in Phases 8–10)."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.models import (
    AccountStatus,
    AttendanceRecord,
    AttendanceSession,
    AuditLog,
    Course,
    Department,
    Hod,
    Student,
    Teacher,
    User,
    UserRole,
)
from backend.app.services.attendance_policy import finalized_counts, summarize
from backend.app.services.attendance_service import today

def _today_percentage(db: Session, *filters) -> float | None:
    """Today's attendance % over finalized sessions, by the configured policy."""
    counts = finalized_counts(db, AttendanceSession.session_date == today(), *filters).get((), {})
    return summarize(counts).percentage


def as_utc(ts: datetime | None) -> datetime | None:
    return ts.replace(tzinfo=UTC) if ts is not None and ts.tzinfo is None else ts


def _active_count(db: Session, model, *filters) -> int:
    return db.scalar(
        select(func.count(model.id)).join(User, User.id == model.user_id)
        .where(User.status == AccountStatus.ACTIVE, *filters)
    ) or 0


# Audit actions that make up the system administrator's activity feed (departments and staff only;
# teacher-to-class assignments are the HOD's and stay in the department audit trail).
_ADMIN_ACTION_PREFIXES = ("department.", "hod.", "teacher.")


def admin_summary(db: Session) -> dict[str, Any]:
    """System administration overview: departments and staff only — no students, no attendance."""
    def staff_count(role: UserRole, status: AccountStatus | None = None) -> int:
        stmt = select(func.count(User.id)).where(User.role == role)
        if role == UserRole.HOD:  # former HODs keep their account row as history
            stmt = stmt.join(Hod, Hod.user_id == User.id).where(Hod.is_current.is_(True))
        if status is not None:
            stmt = stmt.where(User.status == status)
        return db.scalar(stmt) or 0

    without_hod = db.scalar(
        select(func.count(Department.id)).where(
            Department.is_active.is_(True),
            ~select(Hod.id).where(Hod.department_id == Department.id, Hod.is_current.is_(True)).exists(),
        )
    ) or 0
    actor = User.__table__.alias("actor")
    activity = db.execute(
        select(AuditLog.id, AuditLog.action, AuditLog.entity, AuditLog.entity_id, AuditLog.timestamp,
               actor.c.full_name)
        .outerjoin(actor, actor.c.id == AuditLog.user_id)
        .where(or_(*(AuditLog.action.startswith(p) for p in _ADMIN_ACTION_PREFIXES)))
        .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
        .limit(8)
    ).all()
    return {
        "departments": db.scalar(select(func.count(Department.id))) or 0,
        "active_departments": db.scalar(select(func.count(Department.id)).where(Department.is_active.is_(True))) or 0,
        "hods": staff_count(UserRole.HOD),
        "active_hods": staff_count(UserRole.HOD, AccountStatus.ACTIVE),
        "teachers": staff_count(UserRole.TEACHER),
        "active_teachers": staff_count(UserRole.TEACHER, AccountStatus.ACTIVE),
        "suspended_staff": staff_count(UserRole.HOD, AccountStatus.SUSPENDED)
        + staff_count(UserRole.TEACHER, AccountStatus.SUSPENDED),
        "departments_without_hod": without_hod,
        "recent_activity": [
            {"id": r.id, "action": r.action, "entity": r.entity, "entity_id": r.entity_id,
             "timestamp": as_utc(r.timestamp), "actor_name": r.full_name}
            for r in activity
        ],
    }


def hod_summary(db: Session, department_id: int) -> dict[str, Any]:
    pending = db.scalar(
        select(func.count(User.id)).join(Student, Student.user_id == User.id)
        .where(User.status == AccountStatus.PENDING, Student.department_id == department_id)
    )
    return {
        "department_name": db.scalar(select(Department.name).where(Department.id == department_id)),
        "teachers": _active_count(db, Teacher, Teacher.department_id == department_id),
        "students": _active_count(db, Student, Student.department_id == department_id),
        "subjects": db.scalar(
            select(func.count(Course.id)).where(Course.department_id == department_id, Course.is_active.is_(True))
        ) or 0,
        "pending_approvals": pending or 0,
        "today_attendance_pct": _today_percentage(db, AttendanceRecord.department_id == department_id),
    }
