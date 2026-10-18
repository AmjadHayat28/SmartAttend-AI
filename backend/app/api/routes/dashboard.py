from fastapi import APIRouter
from sqlalchemy import select

from backend.app.auth.dependencies import AdminUser, DbSession, HodUser, StudentUser, TeacherUser
from backend.app.core.config import settings
from backend.app.models import (
    AttendanceRecord,
    Course,
    Section,
    Semester,
    StudentCourseEnrollment,
    TeacherCourseAssignment,
)
from backend.app.services import dashboard_service
from backend.app.services.attendance_policy import finalized_counts, policy_description, summarize

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/admin")
def admin_dashboard(_: AdminUser, db: DbSession):
    return dashboard_service.admin_summary(db)


@router.get("/hod")
def hod_dashboard(user: HodUser, db: DbSession):
    return dashboard_service.hod_summary(db, user.department_id)


@router.get("/teacher/classes")
def teacher_classes(user: TeacherUser, db: DbSession):
    """Only classes actively assigned to the logged-in teacher."""
    rows = db.execute(
        select(TeacherCourseAssignment, Course, Section, Semester)
        .join(Course, Course.id == TeacherCourseAssignment.course_id)
        .join(Section, Section.id == TeacherCourseAssignment.section_id)
        .join(Semester, Semester.id == TeacherCourseAssignment.semester_id)
        .where(
            TeacherCourseAssignment.teacher_id == user.teacher_profile.id,
            TeacherCourseAssignment.is_active.is_(True),
            Course.is_active.is_(True),
            Section.is_active.is_(True),
        )
        .order_by(Semester.number, Section.name, Course.title)
    ).all()
    return [
        {
            "assignment_id": a.id,
            "course_id": c.id,
            "course_code": c.code,
            "course_title": c.title,
            "is_lab": c.is_lab,
            "section_id": s.id,
            "section": s.name,
            "semester": sem.number,
            "semester_name": sem.name,
        }
        for a, c, s, sem in rows
    ]


@router.get("/student/subjects")
def student_subjects(user: StudentUser, db: DbSession):
    """Subject-wise attendance over FINALIZED sessions, using the configured policy
    (see services/attendance_policy.py). Drafts never count."""
    student = user.student_profile
    stats = {
        key[0]: summarize(counts)
        for key, counts in finalized_counts(db, AttendanceRecord.student_id == student.id,
                                            group_by=[AttendanceRecord.course_id]).items()
    }
    courses = db.scalars(
        select(Course)
        .join(StudentCourseEnrollment, StudentCourseEnrollment.course_id == Course.id)
        .where(StudentCourseEnrollment.student_id == student.id, StudentCourseEnrollment.is_active.is_(True))
        .order_by(Course.title)
    ).all()
    result = []
    for course in courses:
        s = stats.get(course.id, summarize({}))
        result.append({
            "course_id": course.id,
            "course_code": course.code,
            "course_title": course.title,
            "attended": round(s.attended, 2),
            "conducted": s.conducted,
            "present": s.present,
            "absent": s.absent,
            "late": s.late,
            "excused": s.excused,
            "percentage": s.percentage,
            "low_attendance": s.is_low,
        })
    return {"threshold": settings.LOW_ATTENDANCE_THRESHOLD, "policy": policy_description(), "subjects": result}
