"""Teacher attendance reports for the caller's own active classes.

- Ownership: every report goes through enrollment_service.get_own_assignment (another
  teacher's / removed / unknown assignment → 404). The router admits teachers only.
- A "class" is the assignment's course + section + semester; reports cover every FINALIZED
  session of that class. Drafts and cancelled sessions never count; deleted sessions are gone
  from the database, so they cannot count.
- Percentages and low-attendance flags come only from services/attendance_policy.py.
- Students: everyone currently enrolled, plus anyone unenrolled later who still has finalized
  records in the period (history is never dropped).
"""

import calendar
from collections import Counter
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models import (
    AttendanceRecord,
    AttendanceSession,
    Batch,
    Course,
    Section,
    Semester,
    SessionStatus,
    Student,
    StudentCourseEnrollment,
    TeacherCourseAssignment,
    User,
)
from backend.app.schemas.reports import (
    ClassReport,
    DailyRecord,
    DailyReport,
    DailySession,
    ReportClass,
    StudentHistoryEntry,
    StudentReport,
    StudentReportRow,
)
from backend.app.services.attendance_policy import AttendanceSummary, finalized_counts, summarize
from backend.app.services.enrollment_service import get_own_assignment
from backend.app.services.scoping import not_found


def _bad(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def check_range(date_from: date | None, date_to: date | None) -> None:
    if date_from and date_to and date_from > date_to:
        raise _bad("The start date must be on or before the end date")


def month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _class_info(db: Session, actor: User, assignment: TeacherCourseAssignment) -> ReportClass:
    course = db.get(Course, assignment.course_id)
    section_name, sem_no, batch_name = db.execute(
        select(Section.name, Semester.number, Batch.name)
        .join(Semester, Semester.id == Section.semester_id)
        .join(Batch, Batch.id == Semester.batch_id)
        .where(Section.id == assignment.section_id)
    ).one()
    return ReportClass(
        assignment_id=assignment.id, course_id=course.id, course_code=course.code, course_title=course.title,
        section_id=assignment.section_id, section_name=section_name, semester_number=sem_no, batch_name=batch_name,
        teacher_name=actor.full_name,
    )


def _session_filters(a: TeacherCourseAssignment, date_from: date | None = None, date_to: date | None = None) -> list:
    filters = [AttendanceSession.course_id == a.course_id, AttendanceSession.section_id == a.section_id,
               AttendanceSession.semester_id == a.semester_id, AttendanceSession.department_id == a.department_id]
    if date_from:
        filters.append(AttendanceSession.session_date >= date_from)
    if date_to:
        filters.append(AttendanceSession.session_date <= date_to)
    return filters


def _enrolled_ids(db: Session, a: TeacherCourseAssignment) -> set[int]:
    return set(db.scalars(select(StudentCourseEnrollment.student_id).where(
        StudentCourseEnrollment.course_id == a.course_id, StudentCourseEnrollment.section_id == a.section_id,
        StudentCourseEnrollment.semester_id == a.semester_id, StudentCourseEnrollment.is_active.is_(True))))


def _students(db: Session, ids: set[int]) -> dict[int, tuple[str, str]]:
    if not ids:
        return {}
    rows = db.execute(select(Student.id, Student.registration_no, User.full_name)
                      .join(User, User.id == Student.user_id).where(Student.id.in_(ids))).all()
    return {sid: (reg, name) for sid, reg, name in rows}


def _counts(s: AttendanceSummary) -> dict:
    return {"total_classes": s.total, "present": s.present, "absent": s.absent, "late": s.late,
            "excused": s.excused, "attended": round(s.attended, 2), "conducted": s.conducted,
            "percentage": s.percentage, "low_attendance": s.is_low}


def _matches(q: str | None, reg: str, name: str) -> bool:
    needle = (q or "").strip().lower()
    return not needle or needle in reg.lower() or needle in name.lower()


def class_report(db: Session, actor: User, assignment_id: int, *, date_from: date | None = None,
                 date_to: date | None = None, q: str | None = None) -> ClassReport:
    """Per-student totals over the class's finalized sessions (optionally within a date range)."""
    check_range(date_from, date_to)
    a = get_own_assignment(db, actor, assignment_id)
    filters = _session_filters(a, date_from, date_to)
    by_student = {key[0]: counts for key, counts in
                  finalized_counts(db, *filters, group_by=[AttendanceRecord.student_id]).items()}
    enrolled = _enrolled_ids(db, a)
    people = _students(db, enrolled | set(by_student))

    rows = []
    totals: dict = {}
    for sid, (reg, name) in people.items():
        counts = by_student.get(sid, {})
        for st, n in counts.items():
            totals[st] = totals.get(st, 0) + n
        if _matches(q, reg, name):
            rows.append(StudentReportRow(student_id=sid, registration_no=reg, student_name=name,
                                         currently_enrolled=sid in enrolled, **_counts(summarize(counts))))
    rows.sort(key=lambda r: r.registration_no)
    sessions = db.scalar(select(func.count(AttendanceSession.id))
                         .where(AttendanceSession.status == SessionStatus.FINALIZED, *filters)) or 0
    return ClassReport(
        report_class=_class_info(db, actor, a), threshold=settings.LOW_ATTENDANCE_THRESHOLD,
        date_from=date_from, date_to=date_to, finalized_sessions=sessions, enrolled_students=len(enrolled),
        class_percentage=summarize(totals).percentage,
        low_attendance_students=sum(1 for r in rows if r.low_attendance), students=rows,
    )


def monthly_report(db: Session, actor: User, assignment_id: int, year: int, month: int,
                   q: str | None = None) -> ClassReport:
    first, last = month_range(year, month)
    return class_report(db, actor, assignment_id, date_from=first, date_to=last, q=q)


def daily_report(db: Session, actor: User, assignment_id: int, day: date, q: str | None = None) -> DailyReport:
    """Every finalized session of the class on `day`, by session number, with each student's status."""
    a = get_own_assignment(db, actor, assignment_id)
    rows = db.execute(
        select(AttendanceSession.session_number, AttendanceRecord.student_id, Student.registration_no,
               User.full_name, AttendanceRecord.status)
        .join(AttendanceRecord, AttendanceRecord.session_id == AttendanceSession.id)
        .join(Student, Student.id == AttendanceRecord.student_id)
        .join(User, User.id == Student.user_id)
        .where(AttendanceSession.status == SessionStatus.FINALIZED, AttendanceSession.session_date == day,
               AttendanceRecord.status.is_not(None), *_session_filters(a))
        .order_by(AttendanceSession.session_number, Student.registration_no)
    ).all()
    sessions: dict[int, list] = {}
    for number, sid, reg, name, st in rows:
        sessions.setdefault(number, []).append((sid, reg, name, st))
    out = []
    for number, records in sessions.items():
        s = summarize(Counter(r[3] for r in records))
        out.append(DailySession(
            session_number=number, present=s.present, absent=s.absent, late=s.late, excused=s.excused,
            percentage=s.percentage,
            records=[DailyRecord(student_id=sid, registration_no=reg, student_name=name, status=st)
                     for sid, reg, name, st in records if _matches(q, reg, name)],
        ))
    return DailyReport(report_class=_class_info(db, actor, a), report_date=day, sessions=out)


def student_report(db: Session, actor: User, assignment_id: int, student_id: int, *,
                   date_from: date | None = None, date_to: date | None = None) -> StudentReport:
    """One student of the class: totals plus date-wise history, newest first."""
    check_range(date_from, date_to)
    a = get_own_assignment(db, actor, assignment_id)
    all_time = _session_filters(a)
    has_history = db.scalar(
        select(AttendanceRecord.id).join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
        .where(AttendanceRecord.student_id == student_id, AttendanceSession.status == SessionStatus.FINALIZED,
               *all_time).limit(1))
    enrolled = _enrolled_ids(db, a)
    if student_id not in enrolled and has_history is None:
        # Not in this class (another section/department, or unknown): indistinguishable.
        raise not_found("Student in this class")
    reg, name = _students(db, {student_id})[student_id]
    filters = _session_filters(a, date_from, date_to)
    counts = finalized_counts(db, AttendanceRecord.student_id == student_id, *filters).get((), {})
    history = db.execute(
        select(AttendanceSession.session_date, AttendanceSession.session_number, AttendanceRecord.status)
        .join(AttendanceRecord, AttendanceRecord.session_id == AttendanceSession.id)
        .where(AttendanceRecord.student_id == student_id, AttendanceSession.status == SessionStatus.FINALIZED,
               AttendanceRecord.status.is_not(None), *filters)
        .order_by(AttendanceSession.session_date.desc(), AttendanceSession.session_number.desc())
    ).all()
    return StudentReport(
        report_class=_class_info(db, actor, a), threshold=settings.LOW_ATTENDANCE_THRESHOLD,
        date_from=date_from, date_to=date_to,
        student=StudentReportRow(student_id=student_id, registration_no=reg, student_name=name,
                                 currently_enrolled=student_id in enrolled, **_counts(summarize(counts))),
        records=[StudentHistoryEntry(session_date=d, session_number=n, status=st) for d, n, st in history],
    )

