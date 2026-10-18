"""Enumerations shared by models, schemas and services."""

import enum

from sqlalchemy import Enum as SAEnum


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    HOD = "hod"
    TEACHER = "teacher"
    STUDENT = "student"


class AccountStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REJECTED = "rejected"


class FaceImageType(str, enum.Enum):
    FRONT = "front"
    LEFT = "left"
    RIGHT = "right"
    EXTRA = "extra"


class FaceEnrollmentStatus(str, enum.Enum):
    """Face-enrollment lifecycle — separate from account approval (AccountStatus)."""

    NOT_STARTED = "not_started"  # no face photos yet
    INCOMPLETE = "incomplete"  # draft: photos being added; may or may not meet the minimum yet
    PENDING_REVIEW = "pending_review"  # submitted by the student, awaiting admin/HOD review
    APPROVED = "approved"  # eligible for recognition (Phase 6); photos are locked
    REJECTED = "rejected"  # retake requested; see students.face_review_note


class ImageCheckStatus(str, enum.Enum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


class SessionStatus(str, enum.Enum):
    DRAFT = "draft"  # being taken: roster editable by the session's teacher
    FINALIZED = "finalized"  # official; counts toward percentages; changes only via corrections
    CANCELLED = "cancelled"  # abandoned draft; kept for audit, frees the class/date/session slot


class AttendanceStatus(str, enum.Enum):
    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"
    EXCUSED = "excused"


class AttendanceMethod(str, enum.Enum):
    FACE_RECOGNITION = "face_recognition"  # pre-filled by AI, not yet confirmed by the teacher
    FACE_RECOGNITION_CONFIRMED = "face_recognition_confirmed"  # teacher accepted/assigned an AI suggestion
    MANUAL = "manual"  # set (or left unmarked) by the teacher
    HOD_OVERRIDE = "hod_override"


class RecognitionRunStatus(str, enum.Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


class RecognitionCategory(str, enum.Enum):
    CONFIDENT = "confident"  # pre-filled as Present unless a teacher decision exists
    LOW_CONFIDENCE = "low_confidence"  # suggestion only; the teacher must accept it
    AMBIGUOUS = "ambiguous"  # two candidates too close; the teacher must choose
    DUPLICATE = "duplicate"  # the same student already matched a stronger face in this photo
    NO_MATCH = "no_match"  # unknown face


class FaceDecision(str, enum.Enum):
    """What happened to a detected face's suggestion."""

    APPLIED = "applied"  # confident primary match pre-filled the record
    MANUAL_KEPT = "manual_kept"  # confident match, but the teacher's own decision was preserved
    PENDING = "pending"  # waiting for the teacher (low confidence / ambiguous / duplicate)
    ACCEPTED = "accepted"  # teacher accepted the suggestion
    ASSIGNED = "assigned"  # teacher linked the face to a (different) roster student
    REJECTED = "rejected"  # teacher marked the face unknown / not this student
    NONE = "none"  # unknown face or secondary sighting; nothing to do


def str_enum(enum_cls: type[enum.Enum], length: int = 32) -> SAEnum:
    """Store enum *values* as VARCHAR + CHECK constraint (portable, migration-friendly).

    The CHECK is named ck_<table>_<enum name> via the metadata naming convention.
    """
    return SAEnum(
        enum_cls,
        name=_snake(enum_cls.__name__),
        native_enum=False,
        create_constraint=True,
        length=length,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )


def _snake(name: str) -> str:
    return "".join(f"_{c.lower()}" if c.isupper() and i else c.lower() for i, c in enumerate(name))
