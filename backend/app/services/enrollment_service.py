"""Teacher class assignments (the department's HOD) and student course enrollments (the class's teacher).

Both are soft-removed (is_active = false) so history survives; creating the same pair
again reactivates the existing row instead of duplicating it. Active enrollments for
(course, section) are the attendance roster and the face-recognition candidate list.
"""

from fastapi import HTTPException, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.models import (
    AccountStatus,
    Batch,
    Course,
    Department,
    Section,
    Semester,
    Student,
    StudentCourseEnrollment,
    Teacher,
    TeacherCourseAssignment,
    User,
)
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
from backend.app.services.audit_service import record_audit
from backend.app.services.scoping import apply_scope, get_in_scope, like, not_found, paginate

# Accounts that may hold enrollments; rejected/suspended students are skipped.
_ENROLLABLE = (AccountStatus.ACTIVE, AccountStatus.PENDING)


def _bad(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


# ── Teacher assignments ────────────────────────────────────────────────────


def _assignment_query():
    return (
        select(TeacherCourseAssignment, User.full_name, Teacher.employee_id, Course, Section.name,
               Semester.number, Batch.id, Batch.name, Department.code)
        .join(Teacher, Teacher.id == TeacherCourseAssignment.teacher_id)
        .join(User, User.id == Teacher.user_id)
        .join(Course, Course.id == TeacherCourseAssignment.course_id)
        .join(Section, Section.id == TeacherCourseAssignment.section_id)
        .join(Semester, Semester.id == TeacherCourseAssignment.semester_id)
        .join(Batch, Batch.id == Semester.batch_id)
        .join(Department, Department.id == TeacherCourseAssignment.department_id)
    )


def _assignment_out(row) -> AssignmentOut:
    a, teacher_name, employee_id, course, section_name, sem_no, batch_id, batch_name, code = row
    return AssignmentOut(
        id=a.id, teacher_id=a.teacher_id, teacher_name=teacher_name, employee_id=employee_id,
        course_id=course.id, course_code=course.code, course_title=course.title, is_lab=course.is_lab,
        section_id=a.section_id, section_name=section_name, semester_id=a.semester_id, semester_number=sem_no,
        batch_id=batch_id, batch_name=batch_name, department_id=a.department_id, department_code=code,
        is_active=a.is_active, assigned_at=a.assigned_at,
    )


def list_assignments(db, actor, *, page, page_size, q=None, department_id=None, teacher_id=None,
                     course_id=None, section_id=None, semester_id=None, is_active=True) -> Page[AssignmentOut]:
    stmt = apply_scope(_assignment_query(), TeacherCourseAssignment.department_id, actor, department_id)
    for column, value in ((TeacherCourseAssignment.teacher_id, teacher_id),
                          (TeacherCourseAssignment.course_id, course_id),
                          (TeacherCourseAssignment.section_id, section_id),
                          (TeacherCourseAssignment.semester_id, semester_id)):
        if value is not None:
            stmt = stmt.where(column == value)
    if is_active is not None:
        stmt = stmt.where(TeacherCourseAssignment.is_active.is_(is_active))
    if q:
        pattern = like(q)
        stmt = stmt.where(or_(func.lower(User.full_name).like(pattern, escape="\\"),
                              func.lower(Course.code).like(pattern, escape="\\"),
                              func.lower(Course.title).like(pattern, escape="\\")))
    stmt = stmt.order_by(Batch.name, Semester.number, Section.name, Course.code)
    return paginate(db, stmt, page, page_size, _assignment_out)


def _get_assignment_out(db, assignment_id: int) -> AssignmentOut:
    return _assignment_out(db.execute(
        _assignment_query().where(TeacherCourseAssignment.id == assignment_id)).one())


def create_assignment(db, actor: User, data: AssignmentCreate, request: Request) -> AssignmentOut:
    teacher = get_in_scope(db, Teacher, data.teacher_id, actor, "Teacher")
    course = get_in_scope(db, Course, data.course_id, actor, "Course")
    section = get_in_scope(db, Section, data.section_id, actor, "Section")
    if not (teacher.department_id == course.department_id == section.department_id):
        raise _bad("Teacher, course and section must belong to the same department")
    if teacher.user.status != AccountStatus.ACTIVE:
        raise _bad("Only active teachers can be assigned to classes")
    if not course.is_active or not section.is_active:
        raise _bad("The course and section must both be active")

    existing = db.scalar(select(TeacherCourseAssignment).where(
        TeacherCourseAssignment.teacher_id == teacher.id,
        TeacherCourseAssignment.course_id == course.id,
        TeacherCourseAssignment.section_id == section.id,
    ))
    if existing and existing.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "This teacher is already assigned to this class")
    if existing:
        assignment = existing
        assignment.is_active = True
        assignment.assigned_by_id = actor.id
    else:
        assignment = TeacherCourseAssignment(
            teacher_id=teacher.id, course_id=course.id, section_id=section.id,
            semester_id=section.semester_id, department_id=section.department_id, assigned_by_id=actor.id,
        )
        db.add(assignment)
    db.flush()
    record_audit(db, actor=actor, action="teacher_assignment.created", entity="teacher_assignment",
                 entity_id=assignment.id, department_id=assignment.department_id,
                 new_value={"teacher_id": teacher.id, "course_id": course.id, "section_id": section.id,
                            "semester_id": section.semester_id, "reactivated": existing is not None},
                 request=request)
    db.commit()
    return _get_assignment_out(db, assignment.id)


def remove_assignment(db, actor: User, assignment_id: int, request: Request) -> None:
    assignment = get_in_scope(db, TeacherCourseAssignment, assignment_id, actor, "Assignment")
    if not assignment.is_active:
        raise not_found("Assignment")
    assignment.is_active = False
    record_audit(db, actor=actor, action="teacher_assignment.removed", entity="teacher_assignment",
                 entity_id=assignment.id, department_id=assignment.department_id,
                 old_value={"teacher_id": assignment.teacher_id, "course_id": assignment.course_id,
                            "section_id": assignment.section_id, "is_active": True},
                 new_value={"is_active": False}, request=request)
    db.commit()


# ── Student enrollments (the class's teacher) ──────────────────────────────
#
# A teacher manages enrollments only through one of their own *active* assignments
# (course + section). The student must be placed in that exact section/semester of the
# same department. HODs assign classes; they do not enroll students.


def get_own_assignment(db: Session, actor: User, assignment_id: int) -> TeacherCourseAssignment:
    """The caller's active assignment, or 404 (another teacher's / removed / unknown look the same)."""
    teacher = actor.teacher_profile
    assignment = db.get(TeacherCourseAssignment, assignment_id)
    if (teacher is None or assignment is None or not assignment.is_active
            or assignment.teacher_id != teacher.id or assignment.department_id != teacher.department_id):
        raise not_found("Class")
    return assignment


def _writable_class(db: Session, assignment: TeacherCourseAssignment) -> tuple[Course, Section]:
    course, section = db.get(Course, assignment.course_id), db.get(Section, assignment.section_id)
    if not course.is_active or not section.is_active:
        raise _bad("The course and section must both be active to change enrollments")
    return course, section


def _class_filter(assignment: TeacherCourseAssignment):
    return (StudentCourseEnrollment.course_id == assignment.course_id,
            StudentCourseEnrollment.section_id == assignment.section_id,
            StudentCourseEnrollment.semester_id == assignment.semester_id,
            StudentCourseEnrollment.department_id == assignment.department_id)


def _audit_value(actor: User, assignment: TeacherCourseAssignment, **extra) -> dict:
    return {"teacher_id": assignment.teacher_id, "teacher_user_id": actor.id, "assignment_id": assignment.id,
            "course_id": assignment.course_id, "section_id": assignment.section_id,
            "semester_id": assignment.semester_id, **extra}


def list_teacher_classes(db, actor: User) -> list[AssignmentOut]:
    """The caller's active class assignments (the classes whose enrollments they manage)."""
    stmt = (_assignment_query()
            .where(TeacherCourseAssignment.teacher_id == actor.teacher_profile.id,
                   TeacherCourseAssignment.is_active.is_(True))
            .order_by(Batch.name, Semester.number, Section.name, Course.code))
    return [_assignment_out(row) for row in db.execute(stmt).all()]


def _enrollment_query():
    return (
        select(StudentCourseEnrollment, Student.registration_no, User.full_name, Course, Section.name,
               Semester.number, Batch.name)
        .join(Student, Student.id == StudentCourseEnrollment.student_id)
        .join(User, User.id == Student.user_id)
        .join(Course, Course.id == StudentCourseEnrollment.course_id)
        .join(Section, Section.id == StudentCourseEnrollment.section_id)
        .join(Semester, Semester.id == StudentCourseEnrollment.semester_id)
        .join(Batch, Batch.id == Semester.batch_id)
    )


def _enrollment_out(row) -> EnrollmentOut:
    e, reg_no, name, course, section_name, sem_no, batch_name = row
    return EnrollmentOut(
        id=e.id, student_id=e.student_id, student_name=name, registration_no=reg_no, course_id=course.id,
        course_code=course.code, course_title=course.title, section_id=e.section_id, section_name=section_name,
        semester_id=e.semester_id, semester_number=sem_no, batch_name=batch_name, department_id=e.department_id,
        is_active=e.is_active, created_at=e.created_at,
    )


def _student_search(stmt, q: str | None):
    if q:
        pattern = like(q)
        stmt = stmt.where(or_(func.lower(User.full_name).like(pattern, escape="\\"),
                              func.lower(Student.registration_no).like(pattern, escape="\\")))
    return stmt


def list_enrollments(db, actor: User, assignment_id: int, *, page, page_size, q=None) -> Page[EnrollmentOut]:
    """Students actively enrolled in one of the caller's classes."""
    assignment = get_own_assignment(db, actor, assignment_id)
    stmt = _enrollment_query().where(*_class_filter(assignment), StudentCourseEnrollment.is_active.is_(True))
    stmt = _student_search(stmt, q).order_by(Student.registration_no)
    return paginate(db, stmt, page, page_size, _enrollment_out)


def _section_students(assignment: TeacherCourseAssignment):
    """Students currently placed in the class's section (same semester and department)."""
    return (select(Student).join(User, User.id == Student.user_id)
            .where(Student.section_id == assignment.section_id, Student.semester_id == assignment.semester_id,
                   Student.department_id == assignment.department_id))


def _active_enrolled_ids(assignment: TeacherCourseAssignment):
    return select(StudentCourseEnrollment.student_id).where(
        StudentCourseEnrollment.course_id == assignment.course_id,
        StudentCourseEnrollment.semester_id == assignment.semester_id,
        StudentCourseEnrollment.is_active.is_(True))


def list_candidates(db, actor: User, assignment_id: int, *, page, page_size, q=None) -> Page[EnrollmentCandidate]:
    """Eligible students of the class's section who are not yet enrolled in the course."""
    assignment = get_own_assignment(db, actor, assignment_id)
    stmt = (_section_students(assignment)
            .where(User.status.in_(_ENROLLABLE), Student.id.not_in(_active_enrolled_ids(assignment))))
    stmt = _student_search(stmt, q).order_by(Student.registration_no)
    return paginate(db, stmt, page, page_size, lambda row: EnrollmentCandidate(
        student_id=row[0].id, student_name=row[0].user.full_name, registration_no=row[0].registration_no,
        status=row[0].user.status))


def _enroll(db: Session, student: Student, course: Course) -> tuple[StudentCourseEnrollment, str]:
    """Enroll one student (already validated). Returns (row, outcome) where outcome is
    'created', 'reactivated' or 'existing'."""
    existing = db.scalar(select(StudentCourseEnrollment).where(
        StudentCourseEnrollment.student_id == student.id,
        StudentCourseEnrollment.course_id == course.id,
        StudentCourseEnrollment.semester_id == student.semester_id,
    ))
    if existing and existing.is_active:
        return existing, "existing"
    if existing:
        existing.is_active = True
        existing.section_id = student.section_id
        return existing, "reactivated"
    row = StudentCourseEnrollment(student_id=student.id, course_id=course.id, section_id=student.section_id,
                                  semester_id=student.semester_id, department_id=student.department_id)
    db.add(row)
    return row, "created"


def create_enrollment(db, actor: User, data: EnrollmentCreate, request: Request) -> EnrollmentOut:
    assignment = get_own_assignment(db, actor, data.assignment_id)
    course, _ = _writable_class(db, assignment)
    student = db.scalar(_section_students(assignment).where(Student.id == data.student_id))
    if student is None:
        # Another section, semester or department: never reveal whether the student exists.
        raise not_found("Student in this class's section")
    if student.user.status not in _ENROLLABLE:
        raise _bad(f"Cannot enroll {student.registration_no}: account is {student.user.status.value}")
    enrollment, outcome = _enroll(db, student, course)
    if outcome == "existing":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{student.registration_no} is already enrolled in {course.code} this semester")
    db.flush()
    record_audit(db, actor=actor, action="student_enrollment.created", entity="student_enrollment",
                 entity_id=enrollment.id, department_id=enrollment.department_id,
                 new_value=_audit_value(actor, assignment, student_id=student.id,
                                        registration_no=student.registration_no,
                                        reactivated=outcome == "reactivated"),
                 request=request)
    db.commit()
    return _enrollment_out(db.execute(_enrollment_query().where(StudentCourseEnrollment.id == enrollment.id)).one())


def remove_enrollment(db, actor: User, enrollment_id: int, request: Request) -> None:
    """Remove an active enrollment from one of the caller's classes."""
    enrollment = db.get(StudentCourseEnrollment, enrollment_id)
    teacher = actor.teacher_profile
    assignment = None
    if enrollment is not None and enrollment.is_active and teacher is not None:
        assignment = db.scalar(select(TeacherCourseAssignment).where(
            TeacherCourseAssignment.teacher_id == teacher.id,
            TeacherCourseAssignment.course_id == enrollment.course_id,
            TeacherCourseAssignment.section_id == enrollment.section_id,
            TeacherCourseAssignment.semester_id == enrollment.semester_id,
            TeacherCourseAssignment.department_id == enrollment.department_id,
            TeacherCourseAssignment.is_active.is_(True)))
    if assignment is None:
        raise not_found("Enrollment")
    enrollment.is_active = False
    record_audit(db, actor=actor, action="student_enrollment.removed", entity="student_enrollment",
                 entity_id=enrollment.id, department_id=enrollment.department_id,
                 old_value={"is_active": True},
                 new_value=_audit_value(actor, assignment, student_id=enrollment.student_id, is_active=False),
                 request=request)
    db.commit()


def bulk_enroll(db, actor: User, data: BulkEnrollRequest, request: Request) -> BulkEnrollResult:
    """Enroll every eligible student of the class's section into its course.

    Ineligible (rejected/suspended) students are reported, not fatal. With dry_run nothing is written.
    """
    assignment = get_own_assignment(db, actor, data.assignment_id)
    course, section = _writable_class(db, assignment)
    students = db.scalars(_section_students(assignment).order_by(Student.registration_no)).all()
    eligible = [s for s in students if s.user.status in _ENROLLABLE]
    errors = [f"{s.registration_no} skipped: account is {s.user.status.value}"
              for s in students if s.user.status not in _ENROLLABLE]
    already = set(db.scalars(_active_enrolled_ids(assignment)))
    new_students = [s for s in eligible if s.id not in already]

    summary = BulkEnrollResult(
        assignment_id=assignment.id, course_id=course.id, course_code=course.code, section_id=section.id,
        dry_run=data.dry_run, students_in_section=len(students), students_eligible=len(eligible),
        newly_enrolled=len(new_students), already_enrolled=len(eligible) - len(new_students),
        skipped=len(students) - len(eligible), errors=errors,
    )
    if data.dry_run:
        return summary
    for student in new_students:
        _enroll(db, student, course)
    record_audit(db, actor=actor, action="student_enrollment.bulk", entity="teacher_assignment",
                 entity_id=assignment.id, department_id=assignment.department_id,
                 new_value=_audit_value(actor, assignment, student_ids=[s.id for s in new_students],
                                        newly_enrolled=summary.newly_enrolled,
                                        already_enrolled=summary.already_enrolled, skipped=summary.skipped),
                 request=request)
    db.commit()
    return summary


