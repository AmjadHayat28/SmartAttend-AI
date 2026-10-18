"""Batches, semesters, sections, courses and the scoped structure tree (admin + HOD)."""

from fastapi import APIRouter, Query, Request, status

from backend.app.api.params import Paging
from backend.app.auth.dependencies import AdminOrHod, HodUser, DbSession
from backend.app.schemas.academic import (
    BatchCreate,
    BatchOut,
    BatchUpdate,
    CourseCreate,
    CourseOut,
    CourseUpdate,
    SectionCreate,
    SectionOut,
    SectionUpdate,
    SemesterCreate,
    SemesterOut,
    SemesterUpdate,
    StructureDepartment,
)
from backend.app.schemas.common import Page
from backend.app.services import academic_service as svc

router = APIRouter(tags=["academics"])
CREATED = {"status_code": status.HTTP_201_CREATED}


@router.get("/academics/structure", response_model=list[StructureDepartment])
def structure(user: AdminOrHod, db: DbSession):
    """Department → batch → semester → section tree for the caller's scope (includes inactive)."""
    return svc.academic_structure(db, user)


# Batches
@router.get("/batches", response_model=Page[BatchOut])
def list_batches(user: HodUser, db: DbSession, p: Paging, department_id: int | None = None,
                 is_active: bool | None = None):
    return svc.list_batches(db, user, page=p.page, page_size=p.page_size, q=p.q,
                            department_id=department_id, is_active=is_active)


@router.post("/batches", response_model=BatchOut, **CREATED)
def create_batch(data: BatchCreate, request: Request, user: HodUser, db: DbSession):
    return svc.create_batch(db, user, data, request)


@router.get("/batches/{batch_id}", response_model=BatchOut)
def get_batch(batch_id: int, user: HodUser, db: DbSession):
    return svc.get_batch_out(db, user, batch_id)


@router.patch("/batches/{batch_id}", response_model=BatchOut)
def update_batch(batch_id: int, data: BatchUpdate, request: Request, user: HodUser, db: DbSession):
    return svc.update_batch(db, user, batch_id, data, request)


# Semesters
@router.get("/semesters", response_model=Page[SemesterOut])
def list_semesters(user: HodUser, db: DbSession, p: Paging, department_id: int | None = None,
                   batch_id: int | None = None, is_active: bool | None = None):
    return svc.list_semesters(db, user, page=p.page, page_size=p.page_size, q=p.q,
                              department_id=department_id, batch_id=batch_id, is_active=is_active)


@router.post("/semesters", response_model=SemesterOut, **CREATED)
def create_semester(data: SemesterCreate, request: Request, user: HodUser, db: DbSession):
    return svc.create_semester(db, user, data, request)


@router.get("/semesters/{semester_id}", response_model=SemesterOut)
def get_semester(semester_id: int, user: HodUser, db: DbSession):
    return svc.get_semester_out(db, user, semester_id)


@router.patch("/semesters/{semester_id}", response_model=SemesterOut)
def update_semester(semester_id: int, data: SemesterUpdate, request: Request, user: HodUser, db: DbSession):
    return svc.update_semester(db, user, semester_id, data, request)


# Sections
@router.get("/sections", response_model=Page[SectionOut])
def list_sections(user: HodUser, db: DbSession, p: Paging, department_id: int | None = None,
                  batch_id: int | None = None, semester_id: int | None = None, is_active: bool | None = None):
    return svc.list_sections(db, user, page=p.page, page_size=p.page_size, q=p.q, department_id=department_id,
                             batch_id=batch_id, semester_id=semester_id, is_active=is_active)


@router.post("/sections", response_model=SectionOut, **CREATED)
def create_section(data: SectionCreate, request: Request, user: HodUser, db: DbSession):
    return svc.create_section(db, user, data, request)


@router.get("/sections/{section_id}", response_model=SectionOut)
def get_section(section_id: int, user: HodUser, db: DbSession):
    return svc.get_section_out(db, user, section_id)


@router.patch("/sections/{section_id}", response_model=SectionOut)
def update_section(section_id: int, data: SectionUpdate, request: Request, user: HodUser, db: DbSession):
    return svc.update_section(db, user, section_id, data, request)


# Courses
@router.get("/courses", response_model=Page[CourseOut])
def list_courses(user: HodUser, db: DbSession, p: Paging, department_id: int | None = None,
                 is_active: bool | None = None, semester_number: int | None = Query(None, ge=1, le=12)):
    return svc.list_courses(db, user, page=p.page, page_size=p.page_size, q=p.q, department_id=department_id,
                            is_active=is_active, semester_number=semester_number)


@router.post("/courses", response_model=CourseOut, **CREATED)
def create_course(data: CourseCreate, request: Request, user: HodUser, db: DbSession):
    return svc.create_course(db, user, data, request)


@router.get("/courses/{course_id}", response_model=CourseOut)
def get_course(course_id: int, user: HodUser, db: DbSession):
    return svc.get_course_out(db, user, course_id)


@router.patch("/courses/{course_id}", response_model=CourseOut)
def update_course(course_id: int, data: CourseUpdate, request: Request, user: HodUser, db: DbSession):
    return svc.update_course(db, user, course_id, data, request)
