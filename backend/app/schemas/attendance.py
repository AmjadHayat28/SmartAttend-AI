"""Attendance sessions (Phase 5: manual marking; no recognition).

Every request that changes a draft carries the session `version` it was based on; a stale
version is rejected with 409 so two open tabs cannot silently overwrite each other.
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field

from backend.app.models import AttendanceMethod, AttendanceStatus, SessionStatus, UserRole
from backend.app.schemas.types import UTCDateTime


def _clean_text(value: object) -> object:
    if isinstance(value, str):
        value = " ".join(value.split())
        return value or None
    return value


# The length limit applies to the string branch only (an explicit null clears the note);
# trimming runs first, so "   " also becomes null.
RecordNote = Annotated[Annotated[str, Field(max_length=200)] | None, BeforeValidator(_clean_text)]
SessionNote = Annotated[Annotated[str, Field(max_length=300)] | None, BeforeValidator(_clean_text)]


class AttendanceClassOut(BaseModel):
    """An active teacher assignment the teacher can take attendance for."""

    assignment_id: int
    course_id: int
    course_code: str
    course_title: str
    is_lab: bool
    batch_id: int
    batch_name: str
    semester_id: int
    semester_number: int
    semester_name: str
    section_id: int
    section_name: str
    department_code: str
    enrolled_count: int
    finalized_sessions: int
    attendance_percentage: float | None
    open_draft_session_id: int | None
    last_session_date: date | None


class SessionStart(BaseModel):
    assignment_id: int
    session_date: date
    session_number: int = Field(default=1, ge=1, le=20)


class SummaryOut(BaseModel):
    total: int
    present: int
    absent: int
    late: int
    excused: int
    unmarked: int
    percentage: float | None  # by the configured policy


class RecordOut(BaseModel):
    id: int
    student_id: int
    registration_no: str
    full_name: str
    profile_photo_url: str | None
    status: AttendanceStatus | None
    note: str | None
    method: AttendanceMethod
    confidence: float | None
    updated_at: UTCDateTime
    corrected: bool
    recognition_face_id: int | None = None  # the detected face that set/confirmed this record


class SessionImageOut(BaseModel):
    id: int
    width: int
    height: int
    file_size: int
    uploaded_at: UTCDateTime
    image_url: str  # API-relative; requires Authorization


class ModificationOut(BaseModel):
    id: int
    record_id: int
    registration_no: str
    student_name: str
    old_status: AttendanceStatus | None
    new_status: AttendanceStatus | None
    old_note: str | None
    new_note: str | None
    reason: str
    modified_by_name: str
    modifier_role: UserRole
    modified_at: UTCDateTime


class SessionDetail(BaseModel):
    id: int
    status: SessionStatus
    version: int
    assignment_id: int | None
    teacher_id: int
    teacher_name: str
    course_id: int
    course_code: str
    course_title: str
    is_lab: bool
    department_id: int
    department_code: str
    batch_name: str
    semester_id: int
    semester_name: str
    section_id: int
    section_name: str
    session_date: date
    session_number: int
    note: str | None
    created_at: UTCDateTime
    finalized_at: UTCDateTime | None
    finalized_by_name: str | None
    cancelled_at: UTCDateTime | None
    cancel_reason: str | None
    summary: SummaryOut
    records: list[RecordOut]
    images: list[SessionImageOut]
    max_photos: int
    can_edit: bool  # draft editor (the session's teacher)
    can_correct: bool  # finalized corrections (the session's teacher, within the window)
    correction_deadline: UTCDateTime | None  # for the teacher
    can_delete: bool  # "Delete Attendance" (the session's teacher, within the window)
    modifications: list[ModificationOut]


class SessionStartOut(BaseModel):
    resumed: bool
    added_to_roster: int  # students enrolled since the draft was created
    session: SessionDetail


class SessionListItem(BaseModel):
    id: int
    status: SessionStatus
    session_date: date
    session_number: int
    course_id: int
    course_code: str
    course_title: str
    teacher_id: int
    teacher_name: str
    department_code: str
    batch_name: str
    semester_name: str
    section_name: str
    summary: SummaryOut
    photo_count: int
    created_at: UTCDateTime
    finalized_at: UTCDateTime | None


class RecordChange(BaseModel):
    record_id: int
    status: AttendanceStatus | None = None  # explicit null = back to "not marked"
    note: RecordNote = None


class RecordsUpdate(BaseModel):
    version: int
    changes: list[RecordChange] = Field(min_length=1, max_length=500)


class BulkUpdate(BaseModel):
    version: int
    action: Literal["all_present", "all_absent", "unmarked_absent", "reset"]


class SessionNoteUpdate(BaseModel):
    version: int
    note: SessionNote = None


class VersionedAction(BaseModel):
    version: int


class CancelRequest(VersionedAction):
    reason: SessionNote = None


class DeleteRequest(BaseModel):
    """Delete Attendance: permanently delete one finalized session (reason mandatory).
    `version` is optional; when sent, a stale tab gets 409 instead of deleting newer corrections."""

    reason: Annotated[str, BeforeValidator(_clean_text), Field(min_length=5, max_length=300)]
    version: int | None = None


class CorrectionRequest(BaseModel):
    status: AttendanceStatus
    note: RecordNote = None
    reason: str = Field(min_length=3, max_length=300)
