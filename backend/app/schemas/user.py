from pydantic import BaseModel, ConfigDict, Field

from backend.app.models import AccountStatus, FaceEnrollmentStatus, UserRole
from backend.app.schemas.common import Page  # noqa: F401  (re-exported)
from backend.app.schemas.types import UTCDateTime


class AccountStatusUpdate(BaseModel):
    status: AccountStatus
    reason: str | None = Field(default=None, max_length=500)


class UserListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: UserRole
    status: AccountStatus
    department_id: int | None
    created_at: UTCDateTime


class PendingStudentOut(BaseModel):
    user_id: int
    full_name: str
    email: str
    registration_no: str
    department_id: int
    batch: str
    semester: int
    section: str
    registered_at: UTCDateTime
    # Shown next to account approval; the two are approved separately.
    face_enrollment_status: FaceEnrollmentStatus = FaceEnrollmentStatus.NOT_STARTED
