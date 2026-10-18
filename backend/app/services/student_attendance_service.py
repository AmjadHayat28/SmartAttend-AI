"""Student "My Attendance": subject-wise summary and per-subject history.

The student is always the authenticated account — no student id is ever accepted. Only
subjects the student is actively enrolled in are listed or queryable, and only FINALIZED
sessions count (drafts and cancelled sessions never do). Percentages come from the shared
policy in services/attendance_policy.py so every screen agrees.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models import (
    AttendanceRecord,
    AttendanceSession,
    Course,
    Section,
    SessionStatus,
    Student,
    StudentCourseEnrollment,
    Teacher,
    TeacherCourseAssignment,
    User,
)
from backend.app.schemas.student_attendance import (
    AttendancePolicyOut,
    StudentAttendanceEntry,
    StudentAttendanceOverview,
    StudentSubjectDetail,
    StudentSubjectSummary,
)
from backend.app.services.attendance_policy import finalized_counts, summarize
from backend.app.services.scoping import not_found


def _enrollments(db: Session, student: Student, course_id: int | None = None):
    stmt = (
        select(StudentCourseEnrollment, Course, Section.name)
        .join(Course, Course.id == StudentCourseEnrollment.course_id)
        .join(Section, Section.id == StudentCourseEnrollment.section_id)
        .where(StudentCourseEnrollment.student_id == student.id, StudentCourseEnrollment.is_active.is_(True))
        .order_by(Course.title, Course.code)
    )
    if course_id is not None:
        stmt = stmt.where(StudentCourseEnrollment.course_id == course_id)
    return db.execute(stmt).all()


def _teacher_names(db: Session, enrollments) -> dict[tuple[int, int, int], list[str]]:
    """{(course, section, semester): [teacher names]} from the classes' active assignments."""
    if not enrollments:
        return {}
    rows = db.execute(
        select(TeacherCourseAssignment.course_id, TeacherCourseAssignment.section_id,
               TeacherCourseAssignment.semester_id, User.full_name)
        .join(Teacher, Teacher.id == TeacherCourseAssignment.teacher_id)
        .join(User, User.id == Teacher.user_id)
        .where(TeacherCourseAssignment.is_active.is_(True),
               TeacherCourseAssignment.course_id.in_({e.course_id for e, _, _ in enrollments}))
        .order_by(User.full_name)
    ).all()
    names: dict[tuple[int, int, int], list[str]] = {}
    for course_id, section_id, semester_id, name in rows:
        names.setdefault((course_id, section_id, semester_id), []).append(name)
    return names


def _summaries(db: Session, student: Student, enrollments) -> list[StudentSubjectSummary]:
    counts = finalized_counts(db, AttendanceRecord.student_id == student.id,
                              group_by=[AttendanceRecord.course_id, AttendanceRecord.semester_id])
    teachers = _teacher_names(db, enrollments)
    result = []
    for e, course, section_name in enrollments:
        s = summarize(counts.get((e.course_id, e.semester_id), {}))
        result.append(StudentSubjectSummary(
            course_id=course.id, course_code=course.code, course_title=course.title, section_name=section_name,
            teacher_names=teachers.get((e.course_id, e.section_id, e.semester_id), []),
            total_classes=s.total, present=s.present, absent=s.absent, late=s.late, excused=s.excused,
            attended=round(s.attended, 2), conducted=s.conducted, percentage=s.percentage,
            low_attendance=s.is_low,
        ))
    return result


def _policy() -> AttendancePolicyOut:
    return AttendancePolicyOut(late_weight=settings.ATTENDANCE_LATE_WEIGHT,
                               excused_policy=settings.ATTENDANCE_EXCUSED_POLICY)


def overview(db: Session, student: Student) -> StudentAttendanceOverview:
    return StudentAttendanceOverview(threshold=settings.LOW_ATTENDANCE_THRESHOLD, policy=_policy(),
                                     subjects=_summaries(db, student, _enrollments(db, student)))


def subject_detail(db: Session, student: Student, course_id: int) -> StudentSubjectDetail:
    enrollments = _enrollments(db, student, course_id)
    if not enrollments:
        # Not enrolled (or another department's course): indistinguishable from unknown.
        raise not_found("Subject")
    enrollment = enrollments[0][0]
    rows = db.execute(
        select(AttendanceRecord.attendance_date, AttendanceRecord.session_number, AttendanceRecord.status)
        .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
        .where(AttendanceRecord.student_id == student.id, AttendanceRecord.course_id == course_id,
               AttendanceRecord.semester_id == enrollment.semester_id,
               AttendanceSession.status == SessionStatus.FINALIZED, AttendanceRecord.status.is_not(None))
        .order_by(AttendanceRecord.attendance_date.desc(), AttendanceRecord.session_number.desc(),
                  AttendanceRecord.id.desc())
    ).all()
    return StudentSubjectDetail(
        threshold=settings.LOW_ATTENDANCE_THRESHOLD,
        subject=_summaries(db, student, enrollments)[0],
        records=[StudentAttendanceEntry(session_date=d, session_number=n, status=s) for d, n, s in rows],
    )
