"""HOD, teacher and student management schemas. Passwords are write-only."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from backend.app.models import AccountStatus, FaceEnrollmentStatus
from backend.app.schemas.common import Email, EmployeeId, FullName, Password, Phone, RegistrationNo
from backend.app.schemas.types import UTCDateTime


class _AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int  # profile id (hods.id / teachers.id / students.id)
    user_id: int
    full_name: str
    email: str
    status: AccountStatus
    status_reason: str | None
    department_id: int
    department_name: str
    department_code: str
    last_login_at: UTCDateTime | None
    created_at: UTCDateTime


# ── HODs ────────────────────────────────────────────────────────────────────


class HodCreate(BaseModel):
    full_name: FullName
    email: Email
    password: Password
    employee_id: EmployeeId
    department_id: int
    phone: Phone | None = None
    appointed_on: date | None = None
    # When the department already has a HOD, the request fails unless this is true;
    # the outgoing HOD then loses the post and their account is suspended.
    replace_existing: bool = False


class HodUpdate(BaseModel):
    full_name: FullName | None = None
    email: Email | None = None
    employee_id: EmployeeId | None = None
    phone: Phone | None = None
    appointed_on: date | None = None
    # Moving a HOD to a department (or reinstating a former HOD) follows the same rule.
    department_id: int | None = None
    replace_existing: bool = False


class HodOut(_AccountOut):
    employee_id: str
    phone: str | None
    appointed_on: date | None
    is_current: bool


# ── Teachers ────────────────────────────────────────────────────────────────


class TeacherCreate(BaseModel):
    full_name: FullName
    email: Email
    password: Password
    employee_id: EmployeeId
    designation: str | None = Field(default=None, max_length=100)
    phone: Phone | None = None
    department_id: int | None = None  # super admin: required; HOD: forced to own department


class TeacherUpdate(BaseModel):
    full_name: FullName | None = None
    email: Email | None = None
    employee_id: EmployeeId | None = None
    designation: str | None = Field(default=None, max_length=100)
    phone: Phone | None = None
    department_id: int | None = None  # super admin only


class TeacherOut(_AccountOut):
    employee_id: str
    designation: str | None
    phone: str | None
    assignment_count: int = 0


# ── Students ────────────────────────────────────────────────────────────────


class StudentCreate(BaseModel):
    """Created by an administrator; the account is active immediately."""

    full_name: FullName
    email: Email
    password: Password
    registration_no: RegistrationNo
    department_id: int | None = None
    batch_id: int
    semester_id: int
    section_id: int


class StudentUpdate(BaseModel):
    full_name: FullName | None = None
    email: Email | None = None
    registration_no: RegistrationNo | None = None
    # Academic placement: batch, semester and section are changed together.
    department_id: int | None = None  # super admin only
    batch_id: int | None = None
    semester_id: int | None = None
    section_id: int | None = None


class StudentOut(_AccountOut):
    registration_no: str
    batch_id: int
    batch_name: str
    semester_id: int
    semester_number: int
    semester_name: str
    section_id: int
    section_name: str
    enrollment_count: int = 0
    face_enrollment_status: FaceEnrollmentStatus = FaceEnrollmentStatus.NOT_STARTED
