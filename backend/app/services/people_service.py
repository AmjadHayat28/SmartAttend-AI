"""HOD, teacher and student account management.

Status changes and password resets go through account_service so the same permission
rules apply everywhere. Passwords are hashed here and never written to the audit log.
"""

from fastapi import HTTPException, Request, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from backend.app.auth.security import hash_password
from backend.app.models import (
    AccountStatus,
    Batch,
    Department,
    Hod,
    Section,
    Semester,
    Student,
    StudentCourseEnrollment,
    Teacher,
    TeacherCourseAssignment,
    User,
    UserRole,
)
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
from backend.app.services.audit_service import changes, record_audit, snapshot
from backend.app.services.scoping import apply_scope, get_in_scope, like, not_found, paginate, resolve_department_id

_USER_FIELDS = ("full_name", "email")


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


def _ensure_email_free(db: Session, email: str, exclude_user_id: int | None = None) -> None:
    stmt = select(User.id).where(User.email == email)
    if exclude_user_id:
        stmt = stmt.where(User.id != exclude_user_id)
    if db.scalar(stmt):
        raise _conflict("An account with this email already exists")


def _ensure_employee_id_free(db: Session, employee_id: str, *, hod_id: int | None = None,
                             teacher_id: int | None = None) -> None:
    """Employee IDs are unique across all staff (HODs and teachers)."""
    hod = select(Hod.id).where(Hod.employee_id == employee_id)
    teacher = select(Teacher.id).where(Teacher.employee_id == employee_id)
    if hod_id:
        hod = hod.where(Hod.id != hod_id)
    if teacher_id:
        teacher = teacher.where(Teacher.id != teacher_id)
    if db.scalar(hod) or db.scalar(teacher):
        raise _conflict("This employee ID is already in use")


def _account_fields(user: User, dept: Department) -> dict:
    return dict(
        user_id=user.id, full_name=user.full_name, email=user.email, status=user.status,
        status_reason=user.status_reason, department_name=dept.name, department_code=dept.code,
        last_login_at=user.last_login_at, created_at=user.created_at,
    )


def _search(stmt, q: str | None, *columns):
    if not q:
        return stmt
    pattern = like(q)
    return stmt.where(or_(*(func.lower(c).like(pattern, escape="\\") for c in columns)))


def _update_user_fields(db: Session, user: User, data) -> tuple[dict, dict]:
    before = snapshot(user, *_USER_FIELDS)
    if data.email is not None and data.email != user.email:
        _ensure_email_free(db, data.email, user.id)
        user.email = data.email
    if data.full_name is not None:
        user.full_name = data.full_name
    return changes(before, snapshot(user, *_USER_FIELDS))


# ── HODs (super admin only) ────────────────────────────────────────────────

_HOD_FIELDS = ("employee_id", "phone", "appointed_on", "department_id", "is_current")


def _hod_out(row) -> HodOut:
    hod, user, dept = row
    return HodOut(id=hod.id, department_id=hod.department_id, employee_id=hod.employee_id, phone=hod.phone,
                  appointed_on=hod.appointed_on, is_current=hod.is_current, **_account_fields(user, dept))


def _hod_query():
    return select(Hod, User, Department).join(User, User.id == Hod.user_id).join(
        Department, Department.id == Hod.department_id)


def list_hods(db, *, page, page_size, q=None, status_filter=None, department_id=None,
              is_current=None) -> Page[HodOut]:
    stmt = _search(_hod_query(), q, User.full_name, User.email, Hod.employee_id)
    if status_filter is not None:
        stmt = stmt.where(User.status == status_filter)
    if department_id is not None:
        stmt = stmt.where(Hod.department_id == department_id)
    if is_current is not None:
        stmt = stmt.where(Hod.is_current.is_(is_current))
    stmt = stmt.order_by(Hod.is_current.desc(), Department.name, User.full_name)
    return paginate(db, stmt, page, page_size, _hod_out)


def get_hod(db, hod_id: int) -> HodOut:
    row = db.execute(_hod_query().where(Hod.id == hod_id)).one_or_none()
    if row is None:
        raise not_found("HOD")
    return _hod_out(row)


def _take_hod_post(db, actor: User, hod: Hod | None, department_id: int, replace_existing: bool,
                   request: Request) -> Department:
    """Make `hod` (None = about to be created) the current HOD of `department_id`.
    The outgoing HOD, if any, loses the post and their account is suspended."""
    dept = db.get(Department, department_id)
    if dept is None:
        raise not_found("Department")
    stmt = select(Hod).where(Hod.department_id == department_id, Hod.is_current.is_(True))
    if hod is not None:
        stmt = stmt.where(Hod.id != hod.id)
    incumbent = db.scalar(stmt)
    if incumbent is not None:
        if not replace_existing:
            raise _conflict(
                f"{dept.name} already has a HOD ({incumbent.user.full_name}). "
                "Confirm the replacement to hand over the post."
            )
        incumbent.is_current = False
        old_user = incumbent.user
        old_status = old_user.status
        old_user.status = AccountStatus.SUSPENDED
        old_user.status_reason = f"Replaced as HOD of {dept.name}"
        old_user.token_version += 1
        db.flush()  # release the partial unique index before the new HOD takes the post
        record_audit(db, actor=actor, action="hod.replaced", entity="hod", entity_id=incumbent.id,
                     department_id=dept.id, old_value={"is_current": True, "status": old_status.value},
                     new_value={"is_current": False, "status": AccountStatus.SUSPENDED.value},
                     request=request)
    return dept


def create_hod(db, actor: User, data: HodCreate, request: Request) -> HodOut:
    _ensure_email_free(db, data.email)
    _ensure_employee_id_free(db, data.employee_id)
    _take_hod_post(db, actor, None, data.department_id, data.replace_existing, request)
    user = User(email=data.email, full_name=data.full_name, password_hash=hash_password(data.password),
                role=UserRole.HOD, status=AccountStatus.ACTIVE, approved_by_id=actor.id)
    user.hod_profile = Hod(department_id=data.department_id, employee_id=data.employee_id, phone=data.phone,
                           appointed_on=data.appointed_on, is_current=True)
    db.add(user)
    db.flush()
    record_audit(db, actor=actor, action="hod.created", entity="hod", entity_id=user.hod_profile.id,
                 department_id=data.department_id,
                 new_value={**snapshot(user, *_USER_FIELDS), **snapshot(user.hod_profile, *_HOD_FIELDS)},
                 request=request)
    db.commit()
    return get_hod(db, user.hod_profile.id)


def update_hod(db, actor: User, hod_id: int, data: HodUpdate, request: Request) -> HodOut:
    hod = db.get(Hod, hod_id)
    if hod is None:
        raise not_found("HOD")
    user_old, user_new = _update_user_fields(db, hod.user, data)
    before = snapshot(hod, *_HOD_FIELDS)
    if data.employee_id is not None and data.employee_id != hod.employee_id:
        _ensure_employee_id_free(db, data.employee_id, hod_id=hod.id)
        hod.employee_id = data.employee_id
    for key in ("phone", "appointed_on"):
        if key in data.model_fields_set:
            setattr(hod, key, getattr(data, key))
    if data.department_id is not None and (data.department_id != hod.department_id or not hod.is_current):
        _take_hod_post(db, actor, hod, data.department_id, data.replace_existing, request)
        hod.department_id = data.department_id
        hod.is_current = True
    old, new = changes(before, snapshot(hod, *_HOD_FIELDS))
    if new or user_new:
        record_audit(db, actor=actor, action="hod.updated", entity="hod", entity_id=hod.id,
                     department_id=hod.department_id, old_value={**user_old, **old},
                     new_value={**user_new, **new}, request=request)
    db.commit()
    return get_hod(db, hod.id)


# ── Teachers (super admin: all; HOD: own department) ───────────────────────

_TEACHER_FIELDS = ("employee_id", "designation", "phone", "department_id")


def _teacher_query():
    assignments = select(func.count(TeacherCourseAssignment.id)).where(
        TeacherCourseAssignment.teacher_id == Teacher.id, TeacherCourseAssignment.is_active.is_(True)
    ).scalar_subquery()
    return select(Teacher, User, Department, assignments).join(User, User.id == Teacher.user_id).join(
        Department, Department.id == Teacher.department_id)


def _teacher_out(row) -> TeacherOut:
    teacher, user, dept, assignments = row
    return TeacherOut(id=teacher.id, department_id=teacher.department_id, employee_id=teacher.employee_id,
                      designation=teacher.designation, phone=teacher.phone, assignment_count=assignments,
                      **_account_fields(user, dept))


def list_teachers(db, actor, *, page, page_size, q=None, status_filter=None,
                  department_id=None) -> Page[TeacherOut]:
    stmt = apply_scope(_teacher_query(), Teacher.department_id, actor, department_id)
    stmt = _search(stmt, q, User.full_name, User.email, Teacher.employee_id)
    if status_filter is not None:
        stmt = stmt.where(User.status == status_filter)
    stmt = stmt.order_by(Department.code, User.full_name)
    return paginate(db, stmt, page, page_size, _teacher_out)


def get_teacher(db, actor, teacher_id: int) -> TeacherOut:
    get_in_scope(db, Teacher, teacher_id, actor, "Teacher")
    return _teacher_out(db.execute(_teacher_query().where(Teacher.id == teacher_id)).one())


def create_teacher(db, actor: User, data: TeacherCreate, request: Request) -> TeacherOut:
    department_id = resolve_department_id(db, actor, data.department_id)
    _ensure_email_free(db, data.email)
    _ensure_employee_id_free(db, data.employee_id)
    user = User(email=data.email, full_name=data.full_name, password_hash=hash_password(data.password),
                role=UserRole.TEACHER, status=AccountStatus.ACTIVE, approved_by_id=actor.id)
    user.teacher_profile = Teacher(department_id=department_id, employee_id=data.employee_id,
                                   designation=data.designation, phone=data.phone)
    db.add(user)
    db.flush()
    record_audit(db, actor=actor, action="teacher.created", entity="teacher", entity_id=user.teacher_profile.id,
                 department_id=department_id,
                 new_value={**snapshot(user, *_USER_FIELDS), **snapshot(user.teacher_profile, *_TEACHER_FIELDS)},
                 request=request)
    db.commit()
    return get_teacher(db, actor, user.teacher_profile.id)


def update_teacher(db, actor: User, teacher_id: int, data: TeacherUpdate, request: Request) -> TeacherOut:
    teacher = get_in_scope(db, Teacher, teacher_id, actor, "Teacher")
    user_old, user_new = _update_user_fields(db, teacher.user, data)
    before = snapshot(teacher, *_TEACHER_FIELDS)
    if data.employee_id is not None and data.employee_id != teacher.employee_id:
        _ensure_employee_id_free(db, data.employee_id, teacher_id=teacher.id)
        teacher.employee_id = data.employee_id
    for key in ("designation", "phone"):
        if key in data.model_fields_set:
            setattr(teacher, key, getattr(data, key))
    if data.department_id is not None and data.department_id != teacher.department_id:
        # HODs get 404 here (they can never name another department).
        new_dept = resolve_department_id(db, actor, data.department_id)
        active = db.scalar(select(func.count(TeacherCourseAssignment.id)).where(
            TeacherCourseAssignment.teacher_id == teacher.id, TeacherCourseAssignment.is_active.is_(True)))
        if active:
            raise _conflict("Remove this teacher's active class assignments before moving departments")
        teacher.department_id = new_dept
    old, new = changes(before, snapshot(teacher, *_TEACHER_FIELDS))
    if new or user_new:
        record_audit(db, actor=actor, action="teacher.updated", entity="teacher", entity_id=teacher.id,
                     department_id=teacher.department_id, old_value={**user_old, **old},
                     new_value={**user_new, **new}, request=request)
    db.commit()
    return get_teacher(db, actor, teacher.id)


# ── Students (super admin: all; HOD: own department) ───────────────────────

_STUDENT_FIELDS = ("registration_no", "department_id", "batch_id", "semester_id", "section_id")


def _student_query():
    enrollments = select(func.count(StudentCourseEnrollment.id)).where(
        StudentCourseEnrollment.student_id == Student.id, StudentCourseEnrollment.is_active.is_(True)
    ).scalar_subquery()
    return (
        select(Student, User, Department, Batch.name, Semester.number, Semester.name, Section.name, enrollments)
        .join(User, User.id == Student.user_id)
        .join(Department, Department.id == Student.department_id)
        .join(Batch, Batch.id == Student.batch_id)
        .join(Semester, Semester.id == Student.semester_id)
        .join(Section, Section.id == Student.section_id)
    )


def _student_out(row) -> StudentOut:
    student, user, dept, batch_name, sem_no, sem_name, section_name, enrollments = row
    return StudentOut(
        id=student.id, department_id=student.department_id, registration_no=student.registration_no,
        batch_id=student.batch_id, batch_name=batch_name, semester_id=student.semester_id,
        semester_number=sem_no, semester_name=sem_name, section_id=student.section_id,
        section_name=section_name, enrollment_count=enrollments,
        face_enrollment_status=student.face_enrollment_status, **_account_fields(user, dept),
    )


def validate_placement(db: Session, department_id: int, batch_id: int, semester_id: int,
                       section_id: int) -> Section:
    """batch → semester → section must form one chain inside the department."""
    section = db.get(Section, section_id)
    semester = db.get(Semester, semester_id)
    batch = db.get(Batch, batch_id)
    valid = (
        batch is not None and batch.department_id == department_id
        and semester is not None and semester.batch_id == batch.id
        and section is not None and section.semester_id == semester.id
    )
    if not valid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Batch, semester and section must belong together and to the student's department")
    return section


def list_students(db, actor, *, page, page_size, q=None, status_filter=None, department_id=None,
                  batch_id=None, semester_id=None, section_id=None) -> Page[StudentOut]:
    stmt = apply_scope(_student_query(), Student.department_id, actor, department_id)
    stmt = _search(stmt, q, User.full_name, User.email, Student.registration_no)
    if status_filter is not None:
        stmt = stmt.where(User.status == status_filter)
    for column, value in ((Student.batch_id, batch_id), (Student.semester_id, semester_id),
                          (Student.section_id, section_id)):
        if value is not None:
            stmt = stmt.where(column == value)
    stmt = stmt.order_by(Department.code, Student.registration_no)
    return paginate(db, stmt, page, page_size, _student_out)


def get_student(db, actor, student_id: int) -> StudentOut:
    get_in_scope(db, Student, student_id, actor, "Student")
    return _student_out(db.execute(_student_query().where(Student.id == student_id)).one())


def _ensure_reg_no_free(db, registration_no: str, exclude_id: int | None = None) -> None:
    stmt = select(Student.id).where(Student.registration_no == registration_no)
    if exclude_id:
        stmt = stmt.where(Student.id != exclude_id)
    if db.scalar(stmt):
        raise _conflict("This registration number is already registered")


def create_student(db, actor: User, data: StudentCreate, request: Request) -> StudentOut:
    department_id = resolve_department_id(db, actor, data.department_id)
    _ensure_email_free(db, data.email)
    _ensure_reg_no_free(db, data.registration_no)
    validate_placement(db, department_id, data.batch_id, data.semester_id, data.section_id)
    user = User(email=data.email, full_name=data.full_name, password_hash=hash_password(data.password),
                role=UserRole.STUDENT, status=AccountStatus.ACTIVE, approved_by_id=actor.id)
    user.student_profile = Student(department_id=department_id, batch_id=data.batch_id,
                                   semester_id=data.semester_id, section_id=data.section_id,
                                   registration_no=data.registration_no)
    db.add(user)
    db.flush()
    record_audit(db, actor=actor, action="student.created", entity="student", entity_id=user.student_profile.id,
                 department_id=department_id,
                 new_value={**snapshot(user, *_USER_FIELDS), **snapshot(user.student_profile, *_STUDENT_FIELDS)},
                 request=request)
    db.commit()
    return get_student(db, actor, user.student_profile.id)


def update_student(db, actor: User, student_id: int, data: StudentUpdate, request: Request) -> StudentOut:
    student = get_in_scope(db, Student, student_id, actor, "Student")
    user_old, user_new = _update_user_fields(db, student.user, data)
    before = snapshot(student, *_STUDENT_FIELDS)
    if data.registration_no is not None and data.registration_no != student.registration_no:
        _ensure_reg_no_free(db, data.registration_no, student.id)
        student.registration_no = data.registration_no

    placement = (data.batch_id, data.semester_id, data.section_id)
    moving_department = data.department_id is not None and data.department_id != student.department_id
    if any(v is not None for v in placement) or moving_department:
        if any(v is None for v in placement):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "batch_id, semester_id and section_id must be changed together")
        department_id = student.department_id
        if moving_department:
            department_id = resolve_department_id(db, actor, data.department_id)  # 404 for HODs
            active = db.scalar(select(func.count(StudentCourseEnrollment.id)).where(
                StudentCourseEnrollment.student_id == student.id, StudentCourseEnrollment.is_active.is_(True)))
            if active:
                raise _conflict("Remove this student's course enrollments before moving departments")
        validate_placement(db, department_id, *placement)
        old_semester_id = student.semester_id
        student.department_id = department_id
        student.batch_id, student.semester_id, student.section_id = placement
        if student.semester_id == old_semester_id:
            # Same semester, new section: carry this semester's enrollments to the new section.
            db.execute(update(StudentCourseEnrollment)
                       .where(StudentCourseEnrollment.student_id == student.id,
                              StudentCourseEnrollment.semester_id == student.semester_id)
                       .values(section_id=student.section_id))
        else:
            # New semester: the previous semester's enrollments are finished.
            db.execute(update(StudentCourseEnrollment)
                       .where(StudentCourseEnrollment.student_id == student.id,
                              StudentCourseEnrollment.semester_id != student.semester_id,
                              StudentCourseEnrollment.is_active.is_(True))
                       .values(is_active=False))

    old, new = changes(before, snapshot(student, *_STUDENT_FIELDS))
    if new or user_new:
        record_audit(db, actor=actor, action="student.updated", entity="student", entity_id=student.id,
                     department_id=student.department_id, old_value={**user_old, **old},
                     new_value={**user_new, **new}, request=request)
    db.commit()
    return get_student(db, actor, student.id)
