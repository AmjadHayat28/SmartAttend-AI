"""Student "My Attendance" — the signed-in student's own attendance only.

No student id is accepted anywhere: the student is the authenticated account. Teachers,
HODs and the super admin are refused (403).
"""

from fastapi import APIRouter

from backend.app.auth.dependencies import DbSession, StudentUser
from backend.app.schemas.student_attendance import StudentAttendanceOverview, StudentSubjectDetail
from backend.app.services import student_attendance_service as svc

router = APIRouter(prefix="/student/attendance", tags=["student attendance"])


@router.get("", response_model=StudentAttendanceOverview)
def my_attendance(user: StudentUser, db: DbSession):
    """Subject-wise summary over FINALIZED sessions for the student's active enrollments."""
    return svc.overview(db, user.student_profile)


@router.get("/subjects/{course_id}", response_model=StudentSubjectDetail)
def my_subject_attendance(course_id: int, user: StudentUser, db: DbSession):
    """One enrolled subject's finalized history, newest first (404 if not enrolled)."""
    return svc.subject_detail(db, user.student_profile, course_id)
