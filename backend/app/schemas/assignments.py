from pydantic import BaseModel

from backend.app.models.enums import AccountStatus
from backend.app.schemas.types import UTCDateTime


class AssignmentCreate(BaseModel):
    """Teacher + course + section. Batch, semester and department are derived from the
    section on the server and must match the teacher's and course's department."""

    teacher_id: int
    course_id: int
    section_id: int


class AssignmentOut(BaseModel):
    id: int
    teacher_id: int
    teacher_name: str
    employee_id: str
    course_id: int
    course_code: str
    course_title: str
    is_lab: bool
    section_id: int
    section_name: str
    semester_id: int
    semester_number: int
    batch_id: int
    batch_name: str
    department_id: int
    department_code: str
    is_active: bool
    assigned_at: UTCDateTime


class EnrollmentCreate(BaseModel):
    """Enroll a student of the class's section into one of the teacher's own classes.
    The section/semester come from the assignment and must match the student's placement."""

    assignment_id: int
    student_id: int


class EnrollmentOut(BaseModel):
    id: int
    student_id: int
    student_name: str
    registration_no: str
    course_id: int
    course_code: str
    course_title: str
    section_id: int
    section_name: str
    semester_id: int
    semester_number: int
    batch_name: str
    department_id: int
    is_active: bool
    created_at: UTCDateTime


class EnrollmentCandidate(BaseModel):
    """A student of the class's section who can still be enrolled."""

    student_id: int
    student_name: str
    registration_no: str
    status: AccountStatus


class BulkEnrollRequest(BaseModel):
    """Enroll every eligible student of the class's section into its course."""

    assignment_id: int
    dry_run: bool = False  # preview the outcome without writing anything


class BulkEnrollResult(BaseModel):
    assignment_id: int
    course_id: int
    course_code: str
    section_id: int
    dry_run: bool
    students_in_section: int
    students_eligible: int
    newly_enrolled: int
    already_enrolled: int
    skipped: int  # rejected / suspended accounts
    errors: list[str]
