"""HOD (super admin only), teacher and student management (super admin + HOD)."""

from fastapi import APIRouter, Query, Request, status

from backend.app.api.params import Paging
from backend.app.auth.dependencies import AdminOrHod, HodUser, AdminUser, DbSession
from backend.app.models import AccountStatus
from backend.app.schemas.common import Page
from backend.app.schemas.people import (
    HodCreate,
    HodOut,
    HodUpdate,
    StudentCreate,
    StudentOut,
    StudentUpdate,
    TeacherCreate,
    TeacherOut,
    TeacherUpdate,
)
from backend.app.services import people_service as svc

router = APIRouter(tags=["people"])
CREATED = {"status_code": status.HTTP_201_CREATED}
StatusFilter = Query(None, alias="status")


# HODs
@router.get("/hods", response_model=Page[HodOut])
def list_hods(_: AdminUser, db: DbSession, p: Paging, status_filter: AccountStatus | None = StatusFilter,
              department_id: int | None = None, is_current: bool | None = None):
    return svc.list_hods(db, page=p.page, page_size=p.page_size, q=p.q, status_filter=status_filter,
                         department_id=department_id, is_current=is_current)


@router.post("/hods", response_model=HodOut, **CREATED)
def create_hod(data: HodCreate, request: Request, admin: AdminUser, db: DbSession):
    return svc.create_hod(db, admin, data, request)


@router.get("/hods/{hod_id}", response_model=HodOut)
def get_hod(hod_id: int, _: AdminUser, db: DbSession):
    return svc.get_hod(db, hod_id)


@router.patch("/hods/{hod_id}", response_model=HodOut)
def update_hod(hod_id: int, data: HodUpdate, request: Request, admin: AdminUser, db: DbSession):
    return svc.update_hod(db, admin, hod_id, data, request)


# Teachers
@router.get("/teachers", response_model=Page[TeacherOut])
def list_teachers(user: AdminOrHod, db: DbSession, p: Paging, status_filter: AccountStatus | None = StatusFilter,
                  department_id: int | None = None):
    return svc.list_teachers(db, user, page=p.page, page_size=p.page_size, q=p.q,
                             status_filter=status_filter, department_id=department_id)


@router.post("/teachers", response_model=TeacherOut, **CREATED)
def create_teacher(data: TeacherCreate, request: Request, user: AdminOrHod, db: DbSession):
    return svc.create_teacher(db, user, data, request)


@router.get("/teachers/{teacher_id}", response_model=TeacherOut)
def get_teacher(teacher_id: int, user: AdminOrHod, db: DbSession):
    return svc.get_teacher(db, user, teacher_id)


@router.patch("/teachers/{teacher_id}", response_model=TeacherOut)
def update_teacher(teacher_id: int, data: TeacherUpdate, request: Request, user: AdminOrHod, db: DbSession):
    return svc.update_teacher(db, user, teacher_id, data, request)


# Students
@router.get("/students", response_model=Page[StudentOut])
def list_students(user: HodUser, db: DbSession, p: Paging, status_filter: AccountStatus | None = StatusFilter,
                  department_id: int | None = None, batch_id: int | None = None, semester_id: int | None = None,
                  section_id: int | None = None):
    return svc.list_students(db, user, page=p.page, page_size=p.page_size, q=p.q, status_filter=status_filter,
                             department_id=department_id, batch_id=batch_id, semester_id=semester_id,
                             section_id=section_id)


@router.post("/students", response_model=StudentOut, **CREATED)
def create_student(data: StudentCreate, request: Request, user: HodUser, db: DbSession):
    return svc.create_student(db, user, data, request)


@router.get("/students/{student_id}", response_model=StudentOut)
def get_student(student_id: int, user: HodUser, db: DbSession):
    return svc.get_student(db, user, student_id)


@router.patch("/students/{student_id}", response_model=StudentOut)
def update_student(student_id: int, data: StudentUpdate, request: Request, user: HodUser, db: DbSession):
    return svc.update_student(db, user, student_id, data, request)
