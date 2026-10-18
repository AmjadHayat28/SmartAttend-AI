"""Face-enrollment schemas. Image URLs are API-relative (served with authorisation);
filesystem paths are never exposed."""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from backend.app.models import AccountStatus, FaceEnrollmentStatus, FaceImageType, ImageCheckStatus
from backend.app.schemas.types import UTCDateTime

REQUIRED_POSES = (FaceImageType.FRONT, FaceImageType.LEFT, FaceImageType.RIGHT)


class FacePhotoOut(BaseModel):
    id: int
    pose: FaceImageType
    validation_status: ImageCheckStatus
    validation_message: str | None
    checks: list[dict[str, Any]]
    width: int | None
    height: int | None
    file_size: int | None
    uploaded_at: UTCDateTime
    updated_at: UTCDateTime
    reviewed_at: UTCDateTime | None
    image_url: str  # relative to /api/v1, requires Authorization


class FaceEnrollmentOut(BaseModel):
    student_id: int
    status: FaceEnrollmentStatus
    requirements_met: bool
    missing_poses: list[FaceImageType]
    photo_count: int
    max_photos: int
    max_extra_photos: int
    can_edit: bool
    can_submit: bool
    photos: list[FacePhotoOut]
    profile_photo_url: str | None
    profile_photo_updated_at: UTCDateTime | None
    submitted_at: UTCDateTime | None
    reviewed_at: UTCDateTime | None
    reviewed_by_name: str | None
    review_note: str | None


class FaceEnrollmentDetail(FaceEnrollmentOut):
    """Reviewer view: enrollment plus who the student is."""

    user_id: int
    full_name: str
    email: str
    registration_no: str
    account_status: AccountStatus
    department_id: int
    department_name: str
    department_code: str
    batch_name: str
    semester_name: str
    section_name: str


class FaceEnrollmentListItem(BaseModel):
    student_id: int
    user_id: int
    full_name: str
    registration_no: str
    account_status: AccountStatus
    department_id: int
    department_code: str
    batch_name: str
    semester_name: str
    section_name: str
    status: FaceEnrollmentStatus
    photo_count: int
    requirements_met: bool
    has_profile_photo: bool
    submitted_at: UTCDateTime | None
    reviewed_at: UTCDateTime | None


class FaceReviewReject(BaseModel):
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def strip(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 3:
            raise ValueError("Please give a reason (at least 3 characters)")
        return value
