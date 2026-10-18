"""Teacher class assignments (the department's HOD only) and student course enrollments (the class's teacher)."""

from fastapi import APIRouter, Request, Response, status

from backend.app.api.params import Paging
from backend.app.auth.dependencies import DbSession, HodUser, TeacherUser
from backend.app.schemas.assignments import (
    AssignmentCreate,
    AssignmentOut,
    BulkEnrollRequest,
    BulkEnrollResult,
    EnrollmentCandidate,
    EnrollmentCreate,
    EnrollmentOut,
)
from backend.app.schemas.common import Page
from backend.app.services import enrollment_service as svc

router = APIRouter(tags=["assignments & enrollments"])


@router.get("/assignments", response_model=Page[AssignmentOut])
def list_assignments(user: HodUser, db: DbSession, p: Paging, department_id: int | None = None,
                     teacher_id: int | None = None, course_id: int | None = None, section_id: int | None = None,
                     semester_id: int | None = None, is_active: bool | None = True):
    return svc.list_assignments(db, user, page=p.page, page_size=p.page_size, q=p.q, department_id=department_id,
                                teacher_id=teacher_id, course_id=course_id, section_id=section_id,
                                semester_id=semester_id, is_active=is_active)


@router.post("/assignments", response_model=AssignmentOut, status_code=status.HTTP_201_CREATED)
def create_assignment(data: AssignmentCreate, request: Request, user: HodUser, db: DbSession):
    return svc.create_assignment(db, user, data, request)


@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_assignment(assignment_id: int, request: Request, user: HodUser, db: DbSession):
    svc.remove_assignment(db, user, assignment_id, request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Student enrollments: the class's teacher only (HOD / super admin: 403) ──


@router.get("/enrollments/classes", response_model=list[AssignmentOut])
def list_my_classes(user: TeacherUser, db: DbSession):
    """The caller's active class assignments, whose enrollments they manage."""
    return svc.list_teacher_classes(db, user)


@router.get("/enrollments", response_model=Page[EnrollmentOut])
def list_enrollments(assignment_id: int, user: TeacherUser, db: DbSession, p: Paging):
    """Students enrolled in one of the caller's classes (search by name or registration no.)."""
    return svc.list_enrollments(db, user, assignment_id, page=p.page, page_size=p.page_size, q=p.q)


@router.get("/enrollments/candidates", response_model=Page[EnrollmentCandidate])
def list_candidates(assignment_id: int, user: TeacherUser, db: DbSession, p: Paging):
    """Eligible students of the class's section not yet enrolled in its course."""
    return svc.list_candidates(db, user, assignment_id, page=p.page, page_size=p.page_size, q=p.q)


@router.post("/enrollments", response_model=EnrollmentOut, status_code=status.HTTP_201_CREATED)
def create_enrollment(data: EnrollmentCreate, request: Request, user: TeacherUser, db: DbSession):
    return svc.create_enrollment(db, user, data, request)


@router.post("/enrollments/bulk", response_model=BulkEnrollResult)
def bulk_enroll(data: BulkEnrollRequest, request: Request, user: TeacherUser, db: DbSession):
    """Enroll every eligible student of the class's section into its course. Use dry_run to preview."""
    return svc.bulk_enroll(db, user, data, request)


@router.delete("/enrollments/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_enrollment(enrollment_id: int, request: Request, user: TeacherUser, db: DbSession):
    svc.remove_enrollment(db, user, enrollment_id, request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
