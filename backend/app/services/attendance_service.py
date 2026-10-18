"""Attendance sessions: draft → finalized | cancelled (Phase 5, manual marking only).

Authorisation (enforced here, never only in the UI):
- Teacher: only their own sessions, created from their own *active* assignment; only drafts
  are editable. Corrections after finalizing only within ATTENDANCE_TEACHER_CORRECTION_HOURS.
- Nobody else: HODs and the super admin are refused at the route (403) and are out of scope
  here too. Another teacher's session answers 404, like the rest of the API.
- After the correction window closes, finalized attendance is locked.

Integrity:
- The roster is a snapshot of active enrollments taken when the session starts (newly enrolled
  students are added when a *draft* is resumed); a finalized roster never changes.
- Records start unmarked (NULL); finalizing requires every student to be marked.
- Every roster/note/state change bumps `version`; a stale version → 409 (optimistic locking).
- Finalized records change only through corrections, each written to attendance_modifications
  (old/new value, reason, who, when) and the audit log.
- "Delete Attendance" permanently deletes ONE finalized session — its records, corrections,
  recognition results, photo metadata and photo files — in a single transaction (files are removed
  only after the commit). Only a minimal audit event remains. Its (course, section, date, session
  number) slot is simply free again. Same permission rules as corrections, plus: a teacher only for
  a session they created/finalized and are still assigned to.
No face recognition happens anywhere in this module.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request, status
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models import (
    AccountStatus,
    AttendanceMethod,
    AttendanceModification,
    AttendanceRecognitionFace,
    AttendanceRecognitionRun,
    AttendanceRecord,
    AttendanceSession,
    AttendanceSessionImage,
    AttendanceStatus,
    Batch,
    Course,
    Department,
    Section,
    Semester,
    SessionStatus,
    Student,
    StudentCourseEnrollment,
    Teacher,
    TeacherCourseAssignment,
    User,
    UserRole,
)
from backend.app.schemas.attendance import (
    AttendanceClassOut,
    BulkUpdate,
    CancelRequest,
    CorrectionRequest,
    ModificationOut,
    RecordOut,
    RecordsUpdate,
    SessionDetail,
    SessionImageOut,
    SessionListItem,
    SessionNoteUpdate,
    SessionStart,
    SessionStartOut,
    DeleteRequest,
    SummaryOut,
)
from backend.app.schemas.common import Page
from backend.app.services import storage
from backend.app.services.attendance_policy import finalized_counts, summarize
from backend.app.services.audit_service import record_audit
from backend.app.services.image_validation import ImageRejected, validate_classroom_photo
from backend.app.services.scoping import like, not_found, paginate

_ROSTER_ACCOUNT_STATUSES = (AccountStatus.ACTIVE, AccountStatus.PENDING)


# ── Helpers ────────────────────────────────────────────────────────────────


def today() -> date:
    if settings.APP_TIMEZONE:
        return datetime.now(ZoneInfo(settings.APP_TIMEZONE)).date()
    return datetime.now().date()  # server local time


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(ts: datetime | None) -> datetime | None:
    return ts.replace(tzinfo=UTC) if ts is not None and ts.tzinfo is None else ts


def _teacher(user: User) -> Teacher:
    if user.role != UserRole.TEACHER or user.teacher_profile is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only teachers take attendance")
    return user.teacher_profile


def _active_assignment(db: Session, teacher: Teacher, assignment_id: int | None) -> TeacherCourseAssignment | None:
    if assignment_id is None:
        return None
    return db.scalar(
        select(TeacherCourseAssignment)
        .join(Course, Course.id == TeacherCourseAssignment.course_id)
        .join(Section, Section.id == TeacherCourseAssignment.section_id)
        .where(TeacherCourseAssignment.id == assignment_id, TeacherCourseAssignment.teacher_id == teacher.id,
               TeacherCourseAssignment.is_active.is_(True), Course.is_active.is_(True), Section.is_active.is_(True))
    )


def _can_view(user: User, session: AttendanceSession) -> bool:
    """Only the session's own teacher (never HODs or the super admin)."""
    if user.role == UserRole.TEACHER and user.teacher_profile is not None:
        return session.teacher_id == user.teacher_profile.id
    return False


def _get_session(db: Session, user: User, session_id: int, lock: bool = False) -> AttendanceSession:
    """lock=True: SELECT … FOR UPDATE on PostgreSQL, so every change to one session (edits, photos,
    recognition, finalize, cancel, corrections, delete) runs one at a time and its version/status
    checks see the latest committed state. (SQLite ignores FOR UPDATE; it has a single writer.)"""
    session = db.get(AttendanceSession, session_id, with_for_update=lock or None)
    if session is None or not _can_view(user, session):
        raise not_found("Attendance session")
    return session


def _editable_session(db: Session, user: User, session_id: int, version: int | None = None) -> AttendanceSession:
    """The session's own teacher, a draft, and the assignment still active. Locks the session row
    until the caller commits."""
    session = _get_session(db, user, session_id, lock=True)
    teacher = _teacher(user)
    if session.teacher_id != teacher.id:
        raise not_found("Attendance session")
    if session.status != SessionStatus.DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"This attendance is {session.status.value} and can no longer be edited.")
    if _active_assignment(db, teacher, session.assignment_id) is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are no longer assigned to this class.")
    if version is not None and version != session.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This attendance was changed in another tab or device. Reload to see the latest version.",
        )
    return session


def _bump(session: AttendanceSession) -> None:
    session.version += 1


def _audit(db, user, request, action, session: AttendanceSession, old=None, new=None):
    record_audit(db, actor=user, action=action, entity="attendance_session", entity_id=session.id,
                 department_id=session.department_id, old_value=old, new_value=new, request=request)


def _active_roster(db: Session, course_id: int, section_id: int) -> list[Student]:
    """Students currently enrolled in (course, section) with an account allowed to attend."""
    return list(db.scalars(
        select(Student)
        .join(StudentCourseEnrollment, StudentCourseEnrollment.student_id == Student.id)
        .join(User, User.id == Student.user_id)
        .where(StudentCourseEnrollment.course_id == course_id, StudentCourseEnrollment.section_id == section_id,
               StudentCourseEnrollment.is_active.is_(True), User.status.in_(_ROSTER_ACCOUNT_STATUSES))
        .order_by(Student.registration_no)
    ).all())


def _new_record(session: AttendanceSession, student: Student, user: User) -> AttendanceRecord:
    return AttendanceRecord(
        session_id=session.id, student_id=student.id, teacher_id=session.teacher_id, course_id=session.course_id,
        department_id=session.department_id, semester_id=session.semester_id, section_id=session.section_id,
        attendance_date=session.session_date, session_number=session.session_number, status=None,
        method=AttendanceMethod.MANUAL, created_by_id=user.id,
    )


def _sync_draft_roster(db: Session, session: AttendanceSession, user: User) -> int:
    """Add students enrolled since the draft was created. Never removes anyone."""
    have = set(db.scalars(select(AttendanceRecord.student_id).where(AttendanceRecord.session_id == session.id)))
    added = [s for s in _active_roster(db, session.course_id, session.section_id) if s.id not in have]
    for student in added:
        db.add(_new_record(session, student, user))
    if added:
        _bump(session)
    return len(added)


# ── Read models ────────────────────────────────────────────────────────────


def _summary(counts: dict, total: int) -> SummaryOut:
    s = summarize(counts)
    return SummaryOut(total=total, present=s.present, absent=s.absent, late=s.late, excused=s.excused,
                      unmarked=total - s.total, percentage=s.percentage)


def _session_counts(db: Session, session_ids: list[int]) -> dict[int, tuple[dict, int]]:
    rows = db.execute(
        select(AttendanceRecord.session_id, AttendanceRecord.status, func.count(AttendanceRecord.id))
        .where(AttendanceRecord.session_id.in_(session_ids))
        .group_by(AttendanceRecord.session_id, AttendanceRecord.status)
    ).all()
    out: dict[int, tuple[dict, int]] = {sid: ({}, 0) for sid in session_ids}
    for sid, st, n in rows:
        counts, total = out[sid]
        if st is not None:
            counts[st] = n
        out[sid] = (counts, total + n)
    return out


def _correction_deadline(session: AttendanceSession) -> datetime | None:
    if session.status != SessionStatus.FINALIZED or not session.finalized_at:
        return None
    return _aware(session.finalized_at) + timedelta(hours=settings.ATTENDANCE_TEACHER_CORRECTION_HOURS)


def _can_correct(user: User, session: AttendanceSession) -> bool:
    """The session's teacher, within the correction window; afterwards the attendance is locked."""
    if session.status != SessionStatus.FINALIZED:
        return False
    if user.role == UserRole.TEACHER and user.teacher_profile and session.teacher_id == user.teacher_profile.id:
        deadline = _correction_deadline(session)
        return settings.ATTENDANCE_TEACHER_CORRECTION_HOURS > 0 and deadline is not None and _now() <= deadline
    return False


def _class_assignment(db: Session, teacher: Teacher, course_id: int, section_id: int) -> TeacherCourseAssignment | None:
    """The teacher's active assignment for (course, section), if any."""
    return db.scalar(
        select(TeacherCourseAssignment)
        .join(Course, Course.id == TeacherCourseAssignment.course_id)
        .join(Section, Section.id == TeacherCourseAssignment.section_id)
        .where(TeacherCourseAssignment.teacher_id == teacher.id, TeacherCourseAssignment.course_id == course_id,
               TeacherCourseAssignment.section_id == section_id, TeacherCourseAssignment.is_active.is_(True),
               Course.is_active.is_(True), Section.is_active.is_(True))
    )


def _teacher_owns_finalized(db: Session, user: User, session: AttendanceSession) -> bool:
    """The session's teacher, who created or finalized it and still teaches that class."""
    teacher = user.teacher_profile
    return (
        teacher is not None and session.teacher_id == teacher.id
        and user.id in (session.created_by_id, session.finalized_by_id)
        and _class_assignment(db, teacher, session.course_id, session.section_id) is not None
    )


def _can_delete(db: Session, user: User, session: AttendanceSession) -> bool:
    """Delete Attendance: the session's own teacher, still assigned, within the window."""
    return _can_correct(user, session) and _teacher_owns_finalized(db, user, session)


def session_detail(db: Session, user: User, session: AttendanceSession) -> SessionDetail:
    course = db.get(Course, session.course_id)
    section = db.get(Section, session.section_id)
    semester = db.get(Semester, session.semester_id)
    batch = db.get(Batch, semester.batch_id)
    dept = db.get(Department, session.department_id)
    teacher = db.get(Teacher, session.teacher_id)
    finalized_by = db.get(User, session.finalized_by_id) if session.finalized_by_id else None

    rows = db.execute(
        select(AttendanceRecord, Student.registration_no, User.full_name, Student.profile_photo_path,
               Student.profile_photo_updated_at)
        .join(Student, Student.id == AttendanceRecord.student_id)
        .join(User, User.id == Student.user_id)
        .where(AttendanceRecord.session_id == session.id)
        .order_by(Student.registration_no)
    ).all()
    corrected_ids = set(db.scalars(
        select(AttendanceModification.record_id)
        .join(AttendanceRecord, AttendanceRecord.id == AttendanceModification.record_id)
        .where(AttendanceRecord.session_id == session.id)
    ))
    records = [
        RecordOut(
            id=r.id, student_id=r.student_id, registration_no=reg_no, full_name=name,
            profile_photo_url=(f"/students/{r.student_id}/profile-photo?v={int(_aware(ts).timestamp()) if ts else 0}"
                               if photo else None),
            status=r.status, note=r.note, method=r.method, confidence=r.confidence, updated_at=r.updated_at,
            corrected=r.id in corrected_ids, recognition_face_id=r.recognition_face_id,
        )
        for r, reg_no, name, photo, ts in rows
    ]
    counts: dict = {}
    for r in records:
        if r.status is not None:
            counts[r.status] = counts.get(r.status, 0) + 1

    images = db.scalars(select(AttendanceSessionImage).where(AttendanceSessionImage.session_id == session.id)
                        .order_by(AttendanceSessionImage.created_at, AttendanceSessionImage.id)).all()
    mods = db.execute(
        select(AttendanceModification, Student.registration_no, User.full_name)
        .join(AttendanceRecord, AttendanceRecord.id == AttendanceModification.record_id)
        .join(Student, Student.id == AttendanceRecord.student_id)
        .join(User, User.id == Student.user_id)
        .where(AttendanceRecord.session_id == session.id)
        .order_by(AttendanceModification.modified_at.desc(), AttendanceModification.id.desc())
    ).all()
    modifier_names = {u.id: u.full_name for u in db.scalars(
        select(User).where(User.id.in_({m.modified_by_id for m, _, _ in mods})))} if mods else {}

    editable = (
        session.status == SessionStatus.DRAFT and user.role == UserRole.TEACHER and user.teacher_profile is not None
        and session.teacher_id == user.teacher_profile.id
        and _active_assignment(db, user.teacher_profile, session.assignment_id) is not None
    )
    return SessionDetail(
        id=session.id, status=session.status, version=session.version, assignment_id=session.assignment_id,
        teacher_id=session.teacher_id, teacher_name=teacher.user.full_name, course_id=course.id,
        course_code=course.code, course_title=course.title, is_lab=course.is_lab, department_id=dept.id,
        department_code=dept.code, batch_name=batch.name, semester_id=semester.id, semester_name=semester.name,
        section_id=section.id, section_name=section.name, session_date=session.session_date,
        session_number=session.session_number, note=session.note, created_at=session.created_at,
        finalized_at=session.finalized_at, finalized_by_name=finalized_by.full_name if finalized_by else None,
        cancelled_at=session.cancelled_at, cancel_reason=session.cancel_reason,
        summary=_summary(counts, len(records)), records=records,
        images=[SessionImageOut(id=i.id, width=i.width, height=i.height, file_size=i.file_size,
                                uploaded_at=i.created_at, image_url=f"/attendance/images/{i.id}") for i in images],
        max_photos=settings.ATTENDANCE_MAX_PHOTOS, can_edit=editable, can_correct=_can_correct(user, session),
        correction_deadline=_correction_deadline(session) if user.role == UserRole.TEACHER else None,
        can_delete=_can_delete(db, user, session),
        modifications=[
            ModificationOut(
                id=m.id, record_id=m.record_id, registration_no=reg_no, student_name=name,
                old_status=(m.old_value or {}).get("status"), new_status=(m.new_value or {}).get("status"),
                old_note=(m.old_value or {}).get("note"), new_note=(m.new_value or {}).get("note"),
                reason=m.reason, modified_by_name=modifier_names.get(m.modified_by_id, "Unknown"),
                modifier_role=m.modifier_role, modified_at=m.modified_at,
            )
            for m, reg_no, name in mods
        ],
    )


# ── Teacher: classes and session start ────────────────────────────────────


def list_classes(db: Session, user: User) -> list[AttendanceClassOut]:
    teacher = _teacher(user)
    enrolled = (
        select(func.count(StudentCourseEnrollment.id))
        .join(Student, Student.id == StudentCourseEnrollment.student_id)
        .join(User, User.id == Student.user_id)
        .where(StudentCourseEnrollment.course_id == TeacherCourseAssignment.course_id,
               StudentCourseEnrollment.section_id == TeacherCourseAssignment.section_id,
               StudentCourseEnrollment.is_active.is_(True), User.status.in_(_ROSTER_ACCOUNT_STATUSES))
        .correlate(TeacherCourseAssignment)
        .scalar_subquery()
    )
    rows = db.execute(
        select(TeacherCourseAssignment, Course, Section, Semester, Batch.id, Batch.name, Department.code, enrolled)
        .join(Course, Course.id == TeacherCourseAssignment.course_id)
        .join(Section, Section.id == TeacherCourseAssignment.section_id)
        .join(Semester, Semester.id == Section.semester_id)
        .join(Batch, Batch.id == Semester.batch_id)
        .join(Department, Department.id == TeacherCourseAssignment.department_id)
        .where(TeacherCourseAssignment.teacher_id == teacher.id, TeacherCourseAssignment.is_active.is_(True),
               Course.is_active.is_(True), Section.is_active.is_(True))
        .order_by(Batch.name, Semester.number, Section.name, Course.code)
    ).all()
    result = []
    for a, course, section, semester, batch_id, batch_name, dept_code, enrolled_count in rows:
        class_filter = and_(AttendanceSession.course_id == course.id, AttendanceSession.section_id == section.id)
        stats = summarize(finalized_counts(db, class_filter).get((), {}))
        finalized_n = db.scalar(select(func.count(AttendanceSession.id)).where(
            class_filter, AttendanceSession.status == SessionStatus.FINALIZED)) or 0
        draft_id = db.scalar(select(AttendanceSession.id).where(
            class_filter, AttendanceSession.status == SessionStatus.DRAFT,
            AttendanceSession.teacher_id == teacher.id).order_by(AttendanceSession.session_date.desc()).limit(1))
        last = db.scalar(select(func.max(AttendanceSession.session_date)).where(
            class_filter, AttendanceSession.status != SessionStatus.CANCELLED))
        result.append(AttendanceClassOut(
            assignment_id=a.id, course_id=course.id, course_code=course.code, course_title=course.title,
            is_lab=course.is_lab, batch_id=batch_id, batch_name=batch_name, semester_id=semester.id,
            semester_number=semester.number, semester_name=semester.name, section_id=section.id,
            section_name=section.name, department_code=dept_code, enrolled_count=enrolled_count or 0,
            finalized_sessions=finalized_n, attendance_percentage=stats.percentage,
            open_draft_session_id=draft_id, last_session_date=last,
        ))
    return result


def start_session(db: Session, user: User, data: SessionStart, request: Request,
                  _retry: bool = False) -> SessionStartOut:
    teacher = _teacher(user)
    assignment = _active_assignment(db, teacher, data.assignment_id)
    if assignment is None:
        raise not_found("Class")
    if data.session_date > today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Attendance cannot be taken for a future date.")
    if data.session_date < today() - timedelta(days=settings.ATTENDANCE_MAX_BACKDATE_DAYS):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"Attendance can be started at most {settings.ATTENDANCE_MAX_BACKDATE_DAYS} days back. "
                            "Older attendance cannot be started.")
    if data.session_number > settings.ATTENDANCE_MAX_SESSIONS_PER_DAY:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"Session number must be between 1 and {settings.ATTENDANCE_MAX_SESSIONS_PER_DAY}.")

    existing = db.scalar(select(AttendanceSession).where(
        AttendanceSession.course_id == assignment.course_id, AttendanceSession.section_id == assignment.section_id,
        AttendanceSession.session_date == data.session_date, AttendanceSession.session_number == data.session_number,
        AttendanceSession.status != SessionStatus.CANCELLED,
    ))
    if existing is not None:
        if existing.status == SessionStatus.DRAFT and existing.teacher_id == teacher.id:
            added = _sync_draft_roster(db, existing, user)
            if added:
                _audit(db, user, request, "attendance.roster_synced", existing, new={"added_students": added})
            db.commit()
            return SessionStartOut(resumed=True, added_to_roster=added, session=session_detail(db, user, existing))
        if existing.status == SessionStatus.DRAFT:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Another teacher is already taking attendance for this class, subject, date and session.")
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Attendance for this class, subject, date and session already exists.")

    roster = _active_roster(db, assignment.course_id, assignment.section_id)
    if not roster:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "No students are enrolled in this class yet. Ask your HOD to enroll them first.")
    session = AttendanceSession(
        assignment_id=assignment.id, teacher_id=teacher.id, course_id=assignment.course_id,
        section_id=assignment.section_id, semester_id=assignment.semester_id, department_id=assignment.department_id,
        session_date=data.session_date, session_number=data.session_number, status=SessionStatus.DRAFT,
        version=1, created_by_id=user.id,
    )
    db.add(session)
    try:
        db.flush()
    except IntegrityError:  # the same slot was started a moment ago (double click, two tabs)
        db.rollback()
        if _retry:
            raise
        return start_session(db, user, data, request, _retry=True)  # → resume it, or the usual 409
    for student in roster:
        db.add(_new_record(session, student, user))
    _audit(db, user, request, "attendance.session_created", session,
           new={"course_id": session.course_id, "section_id": session.section_id,
                "session_date": session.session_date.isoformat(), "session_number": session.session_number,
                "roster_size": len(roster)})
    db.commit()
    return SessionStartOut(resumed=False, added_to_roster=0, session=session_detail(db, user, session))


def get_session(db: Session, user: User, session_id: int) -> SessionDetail:
    return session_detail(db, user, _get_session(db, user, session_id))


# ── Teacher: editing a draft ───────────────────────────────────────────────


def update_records(db: Session, user: User, session_id: int, data: RecordsUpdate, request: Request) -> SessionDetail:
    session = _editable_session(db, user, session_id, data.version)
    ids = {c.record_id for c in data.changes}
    records = {r.id: r for r in db.scalars(select(AttendanceRecord).where(
        AttendanceRecord.session_id == session.id, AttendanceRecord.id.in_(ids)))}
    if len(records) != len(ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "One or more students are not on this roster.")
    changed, overridden = [], []
    for change in data.changes:
        record = records[change.record_id]
        before = {"status": record.status.value if record.status else None, "note": record.note}
        if "status" in change.model_fields_set:
            record.status = change.status
        if "note" in change.model_fields_set:
            record.note = change.note
        after = {"status": record.status.value if record.status else None, "note": record.note}
        if after != before:
            entry = {"record_id": record.id, "student_id": record.student_id, "old": before, "new": after}
            if record.method in (AttendanceMethod.FACE_RECOGNITION, AttendanceMethod.FACE_RECOGNITION_CONFIRMED) \
                    and after["status"] != before["status"]:
                entry["overrode"] = record.method.value  # teacher overrode an AI-filled mark
                overridden.append(record.student_id)
            if after["status"] != before["status"]:
                record.method = AttendanceMethod.MANUAL
            record.last_modified_by_id = user.id
            changed.append(entry)
    if changed:
        _bump(session)
        _audit(db, user, request, "attendance.records_updated", session, new={"changes": changed})
    if overridden:
        _audit(db, user, request, "recognition.ai_overridden", session, new={"student_ids": overridden})
    db.commit()
    return session_detail(db, user, session)


_BULK = {
    "all_present": ("all", AttendanceStatus.PRESENT),
    "all_absent": ("all", AttendanceStatus.ABSENT),
    "unmarked_absent": ("unmarked", AttendanceStatus.ABSENT),
    "reset": ("all", None),
}


def bulk_update(db: Session, user: User, session_id: int, data: BulkUpdate, request: Request) -> SessionDetail:
    session = _editable_session(db, user, session_id, data.version)
    scope, new_status = _BULK[data.action]
    stmt = select(AttendanceRecord).where(AttendanceRecord.session_id == session.id)
    if scope == "unmarked":
        stmt = stmt.where(AttendanceRecord.status.is_(None))
    affected = 0
    for record in db.scalars(stmt):
        if record.status != new_status:
            record.status, record.method, record.last_modified_by_id = new_status, AttendanceMethod.MANUAL, user.id
            affected += 1
    if affected:
        _bump(session)
    _audit(db, user, request, "attendance.bulk_update", session, new={"action": data.action, "affected": affected})
    db.commit()
    return session_detail(db, user, session)


def update_note(db: Session, user: User, session_id: int, data: SessionNoteUpdate, request: Request) -> SessionDetail:
    session = _editable_session(db, user, session_id, data.version)
    if session.note != data.note:
        _audit(db, user, request, "attendance.note_changed", session, old={"note": session.note},
               new={"note": data.note})
        session.note = data.note
        _bump(session)
    db.commit()
    return session_detail(db, user, session)


def _no_recognition_running(db: Session, session: AttendanceSession, message: str) -> None:
    """Photos, finalizing and discarding wait while face recognition is analysing the session."""
    from backend.app.services.recognition_service import active_run  # recognition imports this module

    if active_run(db, session.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, message)


def _photos_unlocked(db: Session, session: AttendanceSession) -> None:
    _no_recognition_running(db, session,
                            "Face recognition is analysing the photos. Wait for it to finish, then change photos.")


def add_image(db: Session, user: User, session_id: int, data: bytes, content_type: str | None,
              request: Request) -> SessionDetail:
    # Photos don't take part in version checks: uploads can run alongside roster autosaves.
    session = _editable_session(db, user, session_id)
    _photos_unlocked(db, session)
    count = db.scalar(select(func.count(AttendanceSessionImage.id)).where(
        AttendanceSessionImage.session_id == session.id)) or 0
    if count >= settings.ATTENDANCE_MAX_PHOTOS:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"A session can have at most {settings.ATTENDANCE_MAX_PHOTOS} classroom photos.")
    try:
        processed = validate_classroom_photo(data, content_type)
    except ImageRejected as exc:
        raise HTTPException(exc.status_code, exc.message) from None
    path = storage.save("attendance", session.id, processed.jpeg)
    image = AttendanceSessionImage(session_id=session.id, image_path=path, width=processed.width,
                                   height=processed.height, file_size=len(processed.jpeg), uploaded_by_id=user.id)
    db.add(image)
    try:
        db.flush()
        _audit(db, user, request, "attendance.photo_uploaded", session,
               new={"image_id": image.id, "width": image.width, "height": image.height, "file_size": image.file_size})
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(path)
        raise
    return session_detail(db, user, session)


def remove_image(db: Session, user: User, session_id: int, image_id: int, request: Request) -> SessionDetail:
    session = _editable_session(db, user, session_id)
    image = db.get(AttendanceSessionImage, image_id)
    if image is None or image.session_id != session.id:
        raise not_found("Photo")
    _photos_unlocked(db, session)
    path = image.image_path
    _audit(db, user, request, "attendance.photo_removed", session, old={"image_id": image.id})
    db.delete(image)
    db.commit()
    storage.delete(path)
    return session_detail(db, user, session)


def finalize(db: Session, user: User, session_id: int, version: int, request: Request) -> SessionDetail:
    session = _editable_session(db, user, session_id, version)
    _no_recognition_running(db, session, "Face recognition is still running. Wait for it to finish and review "
                                         "its suggestions before finalizing.")
    unmarked = db.scalar(select(func.count(AttendanceRecord.id)).where(
        AttendanceRecord.session_id == session.id, AttendanceRecord.status.is_(None))) or 0
    if unmarked:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"{unmarked} student(s) are not marked yet. Mark everyone before finalizing.")
    now = _now()
    session.status, session.finalized_at, session.finalized_by_id = SessionStatus.FINALIZED, now, user.id
    _bump(session)
    counts, total = _session_counts(db, [session.id])[session.id]
    summary = _summary(counts, total)
    _audit(db, user, request, "attendance.session_finalized", session,
           new={"total": summary.total, "present": summary.present, "absent": summary.absent,
                "late": summary.late, "excused": summary.excused})
    db.commit()
    return session_detail(db, user, session)


def cancel(db: Session, user: User, session_id: int, data: CancelRequest, request: Request) -> SessionDetail:
    session = _editable_session(db, user, session_id, data.version)
    _no_recognition_running(db, session, "Face recognition is still running. Wait for it to finish before "
                                         "discarding this draft.")
    session.status, session.cancelled_at, session.cancelled_by_id = SessionStatus.CANCELLED, _now(), user.id
    session.cancel_reason = data.reason
    _bump(session)
    _audit(db, user, request, "attendance.session_cancelled", session, new={"reason": data.reason})
    db.commit()
    return session_detail(db, user, session)


# ── Corrections to finalized attendance ────────────────────────────────────


def correct_record(db: Session, user: User, record_id: int, data: CorrectionRequest,
                   request: Request) -> SessionDetail:
    record = db.get(AttendanceRecord, record_id)
    session = db.get(AttendanceSession, record.session_id, with_for_update=True) if record else None
    if session is not None:  # re-read under the lock: a concurrent correction or delete may have won
        record = db.scalar(select(AttendanceRecord).where(AttendanceRecord.id == record_id)
                           .execution_options(populate_existing=True))
    if record is None or session is None or not _can_view(user, session):
        raise not_found("Attendance record")
    if session.status == SessionStatus.CANCELLED:
        raise HTTPException(status.HTTP_409_CONFLICT, "This attendance was cancelled and no longer counts.")
    if session.status != SessionStatus.FINALIZED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only finalized attendance is corrected; edit the draft instead.")
    if not _can_correct(user, session):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "The correction window for this session has closed; this attendance is now locked.")
    before = {"status": record.status.value if record.status else None, "note": record.note}
    after = {"status": data.status.value, "note": data.note if "note" in data.model_fields_set else record.note}
    if after == before:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to change.")
    reason = " ".join(data.reason.split())
    record.status, record.note, record.last_modified_by_id = data.status, after["note"], user.id
    db.add(AttendanceModification(record_id=record.id, modified_by_id=user.id, modifier_role=user.role,
                                  old_value=before, new_value=after, reason=reason))
    _bump(session)
    record_audit(db, actor=user, action="attendance.record_corrected", entity="attendance_record", entity_id=record.id,
                 department_id=session.department_id, old_value=before,
                 new_value={**after, "reason": reason, "session_id": session.id}, request=request)
    db.commit()
    return session_detail(db, user, session)


# ── Delete Attendance (one finalized session, permanently) ─────────────────


def delete_session(db: Session, user: User, session_id: int, data: DeleteRequest, request: Request) -> None:
    """Permanently delete exactly this finalized session and everything that belongs only to it:
    corrections → records → recognition faces → recognition runs → photo metadata → session, in one
    transaction (any failure rolls everything back). Photo files are removed only after the commit,
    so a failed delete never loses evidence. Nothing outside this session is touched: other sessions,
    dates, courses, sections, students, enrollments and assignments stay as they are."""
    session = _get_session(db, user, session_id, lock=True)  # a second, concurrent delete then gets 404
    if session.status != SessionStatus.FINALIZED:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Only finalized attendance can be deleted. Discard a draft from the attendance editor.")
    if not _teacher_owns_finalized(db, user, session):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "You can only delete attendance you took for a class you are still assigned to.")
    if not _can_delete(db, user, session):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "The correction window for this session has closed; this attendance is now locked.")
    if data.version is not None and data.version != session.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This attendance was changed in another tab or device. Reload to see the latest version.",
        )

    course = db.get(Course, session.course_id)
    section = db.get(Section, session.section_id)
    metadata = {
        "session_id": session.id, "course_id": course.id, "course_code": course.code, "course_title": course.title,
        "section_id": section.id, "section_name": section.name, "session_date": session.session_date.isoformat(),
        "session_number": session.session_number, "teacher_id": session.teacher_id,
    }
    image_paths = list(db.scalars(select(AttendanceSessionImage.image_path)
                                  .where(AttendanceSessionImage.session_id == session.id)))
    record_ids = select(AttendanceRecord.id).where(AttendanceRecord.session_id == session.id)
    run_ids = select(AttendanceRecognitionRun.id).where(AttendanceRecognitionRun.session_id == session.id)
    try:
        # Children first, so it works the same with or without database-level ON DELETE CASCADE.
        db.execute(delete(AttendanceModification).where(AttendanceModification.record_id.in_(record_ids)))
        db.execute(delete(AttendanceRecord).where(AttendanceRecord.session_id == session.id))
        db.execute(delete(AttendanceRecognitionFace).where(AttendanceRecognitionFace.run_id.in_(run_ids)))
        db.execute(delete(AttendanceRecognitionRun).where(AttendanceRecognitionRun.session_id == session.id))
        db.execute(delete(AttendanceSessionImage).where(AttendanceSessionImage.session_id == session.id))
        db.execute(delete(AttendanceSession).where(AttendanceSession.id == session.id))
        # Minimal audit event: who deleted which session and why — no student attendance data.
        record_audit(db, actor=user, action="attendance.session_deleted", entity="attendance_session",
                     entity_id=metadata["session_id"], department_id=session.department_id, old_value=metadata,
                     new_value={"reason": data.reason, "deleted_by_role": user.role.value}, request=request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    for path in image_paths:
        storage.delete(path)
    storage.prune_dir("attendance", metadata["session_id"])


# ── Lists ──────────────────────────────────────────────────────────────────


def list_sessions(db: Session, user: User, *, page: int, page_size: int, q: str | None = None,
                  status_filter: SessionStatus | None = None, date_from: date | None = None,
                  date_to: date | None = None, course_id: int | None = None,
                  semester_id: int | None = None, section_id: int | None = None) -> Page[SessionListItem]:
    """The calling teacher's own sessions only. Cancelled sessions are hidden from history
    (they stay in the database for audit); asking for status=cancelled returns nothing."""
    teacher_user = User.__table__.alias("teacher_user")
    stmt = (
        select(AttendanceSession, Course.code, Course.title, teacher_user.c.full_name, Department.code,
               Batch.name, Semester.name, Section.name)
        .join(Course, Course.id == AttendanceSession.course_id)
        .join(Teacher, Teacher.id == AttendanceSession.teacher_id)
        .join(teacher_user, teacher_user.c.id == Teacher.user_id)
        .join(Department, Department.id == AttendanceSession.department_id)
        .join(Section, Section.id == AttendanceSession.section_id)
        .join(Semester, Semester.id == AttendanceSession.semester_id)
        .join(Batch, Batch.id == Semester.batch_id)
    )
    stmt = stmt.where(AttendanceSession.teacher_id == _teacher(user).id,
                      AttendanceSession.status != SessionStatus.CANCELLED)
    for column, value in ((AttendanceSession.status, status_filter), (AttendanceSession.course_id, course_id), (AttendanceSession.semester_id, semester_id),
                          (AttendanceSession.section_id, section_id)):
        if value is not None:
            stmt = stmt.where(column == value)
    if date_from:
        stmt = stmt.where(AttendanceSession.session_date >= date_from)
    if date_to:
        stmt = stmt.where(AttendanceSession.session_date <= date_to)
    if q:
        pattern = like(q)
        stmt = stmt.where(or_(func.lower(Course.code).like(pattern, escape="\\"),
                              func.lower(Course.title).like(pattern, escape="\\"),
                              func.lower(teacher_user.c.full_name).like(pattern, escape="\\")))
    stmt = stmt.order_by(AttendanceSession.session_date.desc(), AttendanceSession.session_number.desc(),
                         AttendanceSession.id.desc())

    page_obj = paginate(db, stmt, page, page_size, lambda row: row)
    ids = [row[0].id for row in page_obj.items]
    counts = _session_counts(db, ids) if ids else {}
    photos = dict(db.execute(select(AttendanceSessionImage.session_id, func.count(AttendanceSessionImage.id))
                             .where(AttendanceSessionImage.session_id.in_(ids))
                             .group_by(AttendanceSessionImage.session_id)).all()) if ids else {}
    items = []
    for s, code, title, teacher_name, dept_code, batch, semester, section in page_obj.items:
        c, total = counts.get(s.id, ({}, 0))
        items.append(SessionListItem(
            id=s.id, status=s.status, session_date=s.session_date, session_number=s.session_number,
            course_id=s.course_id, course_code=code, course_title=title, teacher_id=s.teacher_id,
            teacher_name=teacher_name, department_code=dept_code, batch_name=batch, semester_name=semester,
            section_name=section, summary=_summary(c, total), photo_count=photos.get(s.id, 0),
            created_at=s.created_at, finalized_at=s.finalized_at,
        ))
    return Page(items=items, total=page_obj.total, page=page, page_size=page_size)


# ── Image retrieval ────────────────────────────────────────────────────────


def image_bytes(db: Session, user: User, image_id: int) -> bytes:
    """The session's own teacher only (never HODs, the super admin or students)."""
    image = db.get(AttendanceSessionImage, image_id)
    session = db.get(AttendanceSession, image.session_id) if image else None
    if image is None or session is None or not _can_view(user, session):
        raise not_found("Image")
    try:
        return storage.read(image.image_path)
    except storage.StorageError:
        raise not_found("Image") from None
