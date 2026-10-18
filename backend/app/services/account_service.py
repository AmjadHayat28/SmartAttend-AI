"""Account lifecycle (approve / reject / suspend / reactivate / password reset),
respecting role hierarchy and department isolation."""

from fastapi import HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.auth.dependencies import ensure_department_access, load_user, scoped_department_id
from backend.app.auth.security import hash_password
from backend.app.models import AccountStatus, Batch, Section, Semester, Student, User, UserRole
from backend.app.schemas.user import AccountStatusUpdate, Page, PendingStudentOut
from backend.app.services.audit_service import record_audit

# Which roles each actor may manage. The super admin administers staff (HODs, teachers);
# students belong to their department's HOD. HODs manage teachers and students of their own
# department only (enforced by ensure_department_access).
_MANAGEABLE_ROLES = {
    UserRole.SUPER_ADMIN: {UserRole.HOD, UserRole.TEACHER},
    UserRole.HOD: {UserRole.TEACHER, UserRole.STUDENT},
}


def get_manageable_account(db: Session, actor: User, user_id: int) -> User:
    """Load an account the actor may manage. Accounts in other departments look like 404."""
    target = load_user(db, user_id)
    if target is None or target.id == actor.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if target.department_id is not None:
        ensure_department_access(actor, target.department_id)
    if target.role not in _MANAGEABLE_ROLES.get(actor.role, set()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot manage this account")
    return target


def list_pending_students(db: Session, actor: User, page: int, page_size: int) -> Page[PendingStudentOut]:
    dept_scope = scoped_department_id(actor)
    base = (
        select(User, Student, Batch.name, Semester.number, Section.name)
        .join(Student, Student.user_id == User.id)
        .join(Batch, Batch.id == Student.batch_id)
        .join(Semester, Semester.id == Student.semester_id)
        .join(Section, Section.id == Student.section_id)
        .where(User.status == AccountStatus.PENDING)
    )
    if dept_scope is not None:
        base = base.where(Student.department_id == dept_scope)

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        base.order_by(User.created_at).offset((page - 1) * page_size).limit(page_size)
    ).all()
    items = [
        PendingStudentOut(
            user_id=user.id,
            full_name=user.full_name,
            email=user.email,
            registration_no=student.registration_no,
            department_id=student.department_id,
            batch=batch_name,
            semester=sem_no,
            section=section_name,
            registered_at=user.created_at,
            face_enrollment_status=student.face_enrollment_status,
        )
        for user, student, batch_name, sem_no, section_name in rows
    ]
    return Page(items=items, total=total, page=page, page_size=page_size)


def _status_action(old: AccountStatus, new: AccountStatus) -> str:
    if old == AccountStatus.PENDING and new == AccountStatus.ACTIVE:
        return "approved"
    if new == AccountStatus.REJECTED:
        return "rejected"
    if new == AccountStatus.SUSPENDED:
        return "suspended"
    return "reactivated"


def update_account_status(
    db: Session, actor: User, user_id: int, data: AccountStatusUpdate, request: Request
) -> User:
    target = get_manageable_account(db, actor, user_id)
    old = target.status
    if data.status == AccountStatus.PENDING:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot move an account back to pending")
    if data.status == old:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Account is already {old.value}")
    if data.status == AccountStatus.REJECTED and old != AccountStatus.PENDING:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only pending registrations can be rejected; suspend instead")
    if data.status in (AccountStatus.REJECTED, AccountStatus.SUSPENDED) and not (data.reason or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A reason is required")
    if (
        data.status == AccountStatus.ACTIVE
        and target.role == UserRole.HOD
        and not (target.hod_profile and target.hod_profile.is_current)
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This HOD no longer holds a department. Re-assign them to a department first.",
        )

    target.status = data.status
    target.status_reason = data.reason.strip() if data.reason else None
    if data.status == AccountStatus.ACTIVE and old == AccountStatus.PENDING:
        target.approved_by_id = actor.id
    if data.status != AccountStatus.ACTIVE:
        target.token_version += 1  # kick out any live sessions

    record_audit(
        db, actor=actor, action=f"{target.role.value}.{_status_action(old, data.status)}",
        entity=target.role.value, entity_id=target.id, department_id=target.department_id,
        old_value={"status": old.value}, new_value={"status": data.status.value, "reason": target.status_reason},
        request=request,
    )
    db.commit()
    return target


def reset_password(db: Session, actor: User, user_id: int, new_password: str, request: Request) -> User:
    """Set a new password chosen by an administrator. Revokes all of the user's sessions.
    The password itself is never written to the audit log."""
    target = get_manageable_account(db, actor, user_id)
    target.password_hash = hash_password(new_password)
    target.token_version += 1
    record_audit(
        db, actor=actor, action=f"{target.role.value}.password_reset", entity=target.role.value,
        entity_id=target.id, department_id=target.department_id, request=request,
    )
    db.commit()
    return target
