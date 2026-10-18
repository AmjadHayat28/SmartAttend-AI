"""Batches, semesters, sections and courses — department-scoped CRUD with audit logging.

Records are never hard-deleted (attendance history references them through RESTRICT
foreign keys); they are deactivated with is_active = false instead.
"""

from fastapi import HTTPException, Request, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from backend.app.models import Batch, Course, Department, Section, Semester, Student, User
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
    StructureBatch,
    StructureDepartment,
    StructureSection,
    StructureSemester,
)
from backend.app.schemas.common import Page
from backend.app.services.audit_service import changes, record_audit, snapshot
from backend.app.services.scoping import apply_scope, get_in_scope, like, paginate, resolve_department_id

_BATCH_FIELDS = ("name", "start_year", "end_year", "is_active")
_SEMESTER_FIELDS = ("number", "name", "start_date", "end_date", "is_current", "is_active")
_SECTION_FIELDS = ("name", "capacity", "is_active")
_COURSE_FIELDS = ("code", "title", "credit_hours", "is_lab", "semester_number", "is_active")


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


def _apply(obj, data, fields) -> tuple[dict, dict]:
    """Apply set fields of an update schema and return (old, new) of what changed."""
    before = snapshot(obj, *fields)
    for key, value in data.model_dump(exclude_unset=True).items():
        if key in fields:
            setattr(obj, key, value)
    return changes(before, snapshot(obj, *fields))


def _audit(db, actor, request, action, obj, entity, old=None, new=None):
    record_audit(db, actor=actor, action=action, entity=entity, entity_id=obj.id,
                 department_id=obj.department_id, old_value=old, new_value=new, request=request)


# ── Batches ────────────────────────────────────────────────────────────────


def _batch_out(row) -> BatchOut:
    batch, code, semesters, students = row
    return BatchOut(
        id=batch.id, department_id=batch.department_id, department_code=code, name=batch.name,
        start_year=batch.start_year, end_year=batch.end_year, is_active=batch.is_active,
        semester_count=semesters, student_count=students,
    )


def _batch_query():
    semesters = select(func.count(Semester.id)).where(Semester.batch_id == Batch.id).scalar_subquery()
    students = select(func.count(Student.id)).where(Student.batch_id == Batch.id).scalar_subquery()
    return (
        select(Batch, Department.code, semesters, students)
        .join(Department, Department.id == Batch.department_id)
    )


def _batch_name_taken(db: Session, department_id: int, name: str, exclude_id: int | None = None) -> bool:
    stmt = select(Batch.id).where(Batch.department_id == department_id, func.lower(Batch.name) == name.lower())
    if exclude_id:
        stmt = stmt.where(Batch.id != exclude_id)
    return db.scalar(stmt) is not None


def list_batches(db, user, *, page, page_size, q=None, department_id=None, is_active=None) -> Page[BatchOut]:
    stmt = apply_scope(_batch_query(), Batch.department_id, user, department_id)
    if q:
        stmt = stmt.where(func.lower(Batch.name).like(like(q), escape="\\"))
    if is_active is not None:
        stmt = stmt.where(Batch.is_active.is_(is_active))
    stmt = stmt.order_by(Department.code, Batch.start_year.desc(), Batch.name)
    return paginate(db, stmt, page, page_size, _batch_out)


def get_batch_out(db, user, batch_id) -> BatchOut:
    get_in_scope(db, Batch, batch_id, user, "Batch")
    return _batch_out(db.execute(_batch_query().where(Batch.id == batch_id)).one())


def create_batch(db, user: User, data: BatchCreate, request: Request) -> BatchOut:
    department_id = resolve_department_id(db, user, data.department_id)
    if _batch_name_taken(db, department_id, data.name):
        raise _conflict(f'Batch "{data.name}" already exists in this department')
    batch = Batch(department_id=department_id, name=data.name, start_year=data.start_year,
                  end_year=data.end_year, is_active=data.is_active)
    db.add(batch)
    db.flush()
    _audit(db, user, request, "batch.created", batch, "batch", new=snapshot(batch, *_BATCH_FIELDS))
    db.commit()
    return get_batch_out(db, user, batch.id)


def update_batch(db, user: User, batch_id: int, data: BatchUpdate, request: Request) -> BatchOut:
    batch = get_in_scope(db, Batch, batch_id, user, "Batch")
    if data.name is not None and _batch_name_taken(db, batch.department_id, data.name, batch.id):
        raise _conflict(f'Batch "{data.name}" already exists in this department')
    old, new = _apply(batch, data, _BATCH_FIELDS)
    if batch.end_year is not None and batch.end_year < batch.start_year:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "end_year cannot be before start_year")
    if new:
        _audit(db, user, request, "batch.updated", batch, "batch", old, new)
    db.commit()
    return get_batch_out(db, user, batch.id)


# ── Semesters ──────────────────────────────────────────────────────────────


def _semester_query():
    sections = select(func.count(Section.id)).where(Section.semester_id == Semester.id).scalar_subquery()
    return (
        select(Semester, Batch.name, Department.code, sections)
        .join(Batch, Batch.id == Semester.batch_id)
        .join(Department, Department.id == Semester.department_id)
    )


def _semester_out(row) -> SemesterOut:
    sem, batch_name, code, sections = row
    return SemesterOut(
        id=sem.id, batch_id=sem.batch_id, batch_name=batch_name, department_id=sem.department_id,
        department_code=code, number=sem.number, name=sem.name, start_date=sem.start_date,
        end_date=sem.end_date, is_current=sem.is_current, is_active=sem.is_active, section_count=sections,
    )


def _ensure_semester_number_free(db, batch_id: int, number: int, exclude_id: int | None = None) -> None:
    stmt = select(Semester.id).where(Semester.batch_id == batch_id, Semester.number == number)
    if exclude_id:
        stmt = stmt.where(Semester.id != exclude_id)
    if db.scalar(stmt):
        raise _conflict(f"Semester {number} already exists for this batch")


def _make_only_current(db, semester: Semester) -> None:
    """A batch has at most one current semester."""
    db.execute(
        update(Semester)
        .where(Semester.batch_id == semester.batch_id, Semester.id != semester.id)
        .values(is_current=False)
    )


def list_semesters(db, user, *, page, page_size, q=None, department_id=None, batch_id=None,
                   is_active=None) -> Page[SemesterOut]:
    stmt = apply_scope(_semester_query(), Semester.department_id, user, department_id)
    if batch_id is not None:
        stmt = stmt.where(Semester.batch_id == batch_id)
    if q:
        stmt = stmt.where(or_(func.lower(Semester.name).like(like(q), escape="\\"),
                              func.lower(Batch.name).like(like(q), escape="\\")))
    if is_active is not None:
        stmt = stmt.where(Semester.is_active.is_(is_active))
    stmt = stmt.order_by(Department.code, Batch.start_year.desc(), Batch.name, Semester.number)
    return paginate(db, stmt, page, page_size, _semester_out)


def get_semester_out(db, user, semester_id) -> SemesterOut:
    get_in_scope(db, Semester, semester_id, user, "Semester")
    return _semester_out(db.execute(_semester_query().where(Semester.id == semester_id)).one())


def create_semester(db, user: User, data: SemesterCreate, request: Request) -> SemesterOut:
    batch = get_in_scope(db, Batch, data.batch_id, user, "Batch")
    _ensure_semester_number_free(db, batch.id, data.number)
    semester = Semester(
        batch_id=batch.id, department_id=batch.department_id, number=data.number,
        name=data.name or f"Semester {data.number}", start_date=data.start_date, end_date=data.end_date,
        is_current=data.is_current, is_active=data.is_active,
    )
    db.add(semester)
    db.flush()
    if semester.is_current:
        _make_only_current(db, semester)
    _audit(db, user, request, "semester.created", semester, "semester",
           new={"batch_id": batch.id, **snapshot(semester, *_SEMESTER_FIELDS)})
    db.commit()
    return get_semester_out(db, user, semester.id)


def update_semester(db, user: User, semester_id: int, data: SemesterUpdate, request: Request) -> SemesterOut:
    semester = get_in_scope(db, Semester, semester_id, user, "Semester")
    if data.number is not None and data.number != semester.number:
        _ensure_semester_number_free(db, semester.batch_id, data.number, semester.id)
    old, new = _apply(semester, data, _SEMESTER_FIELDS)
    if not semester.name:  # cleared name falls back to the default, as on create
        semester.name = f"Semester {semester.number}"
        old, new = changes({**old, "name": old.get("name", semester.name)}, {**new, "name": semester.name})
    if semester.start_date and semester.end_date and semester.end_date < semester.start_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "end_date cannot be before start_date")
    if semester.is_current and new.get("is_current"):
        _make_only_current(db, semester)
    if new:
        _audit(db, user, request, "semester.updated", semester, "semester", old, new)
    db.commit()
    return get_semester_out(db, user, semester.id)


# ── Sections ───────────────────────────────────────────────────────────────


def _section_query():
    students = select(func.count(Student.id)).where(Student.section_id == Section.id).scalar_subquery()
    return (
        select(Section, Semester, Batch.id, Batch.name, Department.code, students)
        .join(Semester, Semester.id == Section.semester_id)
        .join(Batch, Batch.id == Semester.batch_id)
        .join(Department, Department.id == Section.department_id)
    )


def _section_out(row) -> SectionOut:
    sec, sem, batch_id, batch_name, code, students = row
    return SectionOut(
        id=sec.id, name=sec.name, capacity=sec.capacity, is_active=sec.is_active, semester_id=sem.id,
        semester_number=sem.number, semester_name=sem.name, batch_id=batch_id, batch_name=batch_name,
        department_id=sec.department_id, department_code=code, student_count=students,
    )


def _ensure_section_name_free(db, semester_id: int, name: str, exclude_id: int | None = None) -> None:
    stmt = select(Section.id).where(Section.semester_id == semester_id, Section.name == name)
    if exclude_id:
        stmt = stmt.where(Section.id != exclude_id)
    if db.scalar(stmt):
        raise _conflict(f'Section "{name}" already exists for this batch and semester')


def list_sections(db, user, *, page, page_size, q=None, department_id=None, batch_id=None,
                  semester_id=None, is_active=None) -> Page[SectionOut]:
    stmt = apply_scope(_section_query(), Section.department_id, user, department_id)
    if batch_id is not None:
        stmt = stmt.where(Semester.batch_id == batch_id)
    if semester_id is not None:
        stmt = stmt.where(Section.semester_id == semester_id)
    if q:
        stmt = stmt.where(func.lower(Section.name).like(like(q), escape="\\"))
    if is_active is not None:
        stmt = stmt.where(Section.is_active.is_(is_active))
    stmt = stmt.order_by(Department.code, Batch.start_year.desc(), Batch.name, Semester.number, Section.name)
    return paginate(db, stmt, page, page_size, _section_out)


def get_section_out(db, user, section_id) -> SectionOut:
    get_in_scope(db, Section, section_id, user, "Section")
    return _section_out(db.execute(_section_query().where(Section.id == section_id)).one())


def create_section(db, user: User, data: SectionCreate, request: Request) -> SectionOut:
    semester = get_in_scope(db, Semester, data.semester_id, user, "Semester")
    if (data.batch_id is not None and data.batch_id != semester.batch_id) or (
        data.department_id is not None and data.department_id != semester.department_id
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Semester does not belong to the selected batch/department")
    _ensure_section_name_free(db, semester.id, data.name)
    section = Section(semester_id=semester.id, department_id=semester.department_id, name=data.name,
                      capacity=data.capacity, is_active=data.is_active)
    db.add(section)
    db.flush()
    _audit(db, user, request, "section.created", section, "section",
           new={"semester_id": semester.id, "batch_id": semester.batch_id, **snapshot(section, *_SECTION_FIELDS)})
    db.commit()
    return get_section_out(db, user, section.id)


def update_section(db, user: User, section_id: int, data: SectionUpdate, request: Request) -> SectionOut:
    section = get_in_scope(db, Section, section_id, user, "Section")
    if data.name is not None and data.name != section.name:
        _ensure_section_name_free(db, section.semester_id, data.name, section.id)
    old, new = _apply(section, data, _SECTION_FIELDS)
    if new:
        _audit(db, user, request, "section.updated", section, "section", old, new)
    db.commit()
    return get_section_out(db, user, section.id)


# ── Courses ────────────────────────────────────────────────────────────────


def _course_out(row) -> CourseOut:
    course, code = row
    return CourseOut(
        id=course.id, department_id=course.department_id, department_code=code, code=course.code,
        title=course.title, credit_hours=course.credit_hours, is_lab=course.is_lab,
        semester_number=course.semester_number, is_active=course.is_active,
    )


def _course_query():
    return select(Course, Department.code).join(Department, Department.id == Course.department_id)


def _ensure_course_code_free(db, department_id: int, code: str, exclude_id: int | None = None) -> None:
    stmt = select(Course.id).where(Course.department_id == department_id, Course.code == code)
    if exclude_id:
        stmt = stmt.where(Course.id != exclude_id)
    if db.scalar(stmt):
        raise _conflict(f'Course code "{code}" already exists in this department')


def list_courses(db, user, *, page, page_size, q=None, department_id=None, is_active=None,
                 semester_number=None) -> Page[CourseOut]:
    stmt = apply_scope(_course_query(), Course.department_id, user, department_id)
    if q:
        pattern = like(q)
        stmt = stmt.where(or_(func.lower(Course.code).like(pattern, escape="\\"),
                              func.lower(Course.title).like(pattern, escape="\\")))
    if is_active is not None:
        stmt = stmt.where(Course.is_active.is_(is_active))
    if semester_number is not None:
        stmt = stmt.where(Course.semester_number == semester_number)
    stmt = stmt.order_by(Department.code, Course.code)
    return paginate(db, stmt, page, page_size, _course_out)


def get_course_out(db, user, course_id) -> CourseOut:
    get_in_scope(db, Course, course_id, user, "Course")
    return _course_out(db.execute(_course_query().where(Course.id == course_id)).one())


def create_course(db, user: User, data: CourseCreate, request: Request) -> CourseOut:
    department_id = resolve_department_id(db, user, data.department_id)
    _ensure_course_code_free(db, department_id, data.code)
    course = Course(department_id=department_id, code=data.code, title=data.title,
                    credit_hours=data.credit_hours, is_lab=data.is_lab,
                    semester_number=data.semester_number, is_active=data.is_active)
    db.add(course)
    db.flush()
    _audit(db, user, request, "course.created", course, "course", new=snapshot(course, *_COURSE_FIELDS))
    db.commit()
    return get_course_out(db, user, course.id)


def update_course(db, user: User, course_id: int, data: CourseUpdate, request: Request) -> CourseOut:
    course = get_in_scope(db, Course, course_id, user, "Course")
    if data.code is not None and data.code != course.code:
        _ensure_course_code_free(db, course.department_id, data.code, course.id)
    old, new = _apply(course, data, _COURSE_FIELDS)
    if new:
        _audit(db, user, request, "course.updated", course, "course", old, new)
    db.commit()
    return get_course_out(db, user, course.id)


# ── Structure tree (cascading dropdowns) ───────────────────────────────────


def academic_structure(db: Session, user: User) -> list[StructureDepartment]:
    stmt = (
        select(Department)
        .options(selectinload(Department.batches).selectinload(Batch.semesters).selectinload(Semester.sections))
        .order_by(Department.name)
    )
    stmt = apply_scope(stmt, Department.id, user)
    return [
        StructureDepartment(
            id=d.id, name=d.name, code=d.code, is_active=d.is_active,
            batches=[
                StructureBatch(
                    id=b.id, name=b.name, is_active=b.is_active,
                    semesters=[
                        StructureSemester(
                            id=s.id, number=s.number, name=s.name, is_active=s.is_active,
                            is_current=s.is_current,
                            sections=[StructureSection(id=x.id, name=x.name, is_active=x.is_active)
                                      for x in sorted(s.sections, key=lambda x: x.name)],
                        )
                        for s in sorted(b.semesters, key=lambda s: s.number)
                    ],
                )
                for b in sorted(d.batches, key=lambda b: (-b.start_year, b.name))
            ],
        )
        for d in db.scalars(stmt).all()
    ]
