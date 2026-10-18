"""Attendance sessions, roster records, classroom photos and the modification trail."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Boolean,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database.base import Base, TimestampMixin
from backend.app.models.enums import (
    AttendanceMethod,
    AttendanceStatus,
    FaceDecision,
    RecognitionCategory,
    RecognitionRunStatus,
    SessionStatus,
    UserRole,
    str_enum,
)

if TYPE_CHECKING:
    from backend.app.models.academic import Course, Section
    from backend.app.models.people import Student, Teacher

JSONType = JSON().with_variant(JSONB(), "postgresql")


class AttendanceSession(TimestampMixin, Base):
    """One lecture/lab of a course for a section on a date.

    `session_number` distinguishes multiple lectures of the same course on the same day.
    At most one non-cancelled session may exist per (course, section, date, session number):
    a partial unique index, so a cancelled draft frees its slot while staying in history.
    `version` is bumped on every roster/note/state change for optimistic locking.
    """

    __tablename__ = "attendance_sessions"
    __table_args__ = (
        Index(
            "uq_attendance_sessions_active_slot",
            "course_id", "section_id", "session_date", "session_number",
            unique=True,
            postgresql_where=text("status <> 'cancelled'"),
            sqlite_where=text("status <> 'cancelled'"),
        ),
        CheckConstraint("session_number >= 1", name="session_number_positive"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("teacher_course_assignments.id", ondelete="SET NULL")
    )
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id", ondelete="RESTRICT"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"), index=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="RESTRICT"), index=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id", ondelete="RESTRICT"))
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    session_date: Mapped[date] = mapped_column(Date, index=True)
    session_number: Mapped[int] = mapped_column(SmallInteger, default=1)
    start_time: Mapped[time | None] = mapped_column(Time)
    status: Mapped[SessionStatus] = mapped_column(
        str_enum(SessionStatus), default=SessionStatus.DRAFT, index=True
    )
    note: Mapped[str | None] = mapped_column(String(300))  # e.g. "Quiz in the first 20 minutes"
    faces_detected: Mapped[int | None] = mapped_column(Integer)  # Phase 6
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

    teacher: Mapped[Teacher] = relationship()
    course: Mapped[Course] = relationship()
    section: Mapped[Section] = relationship()
    records: Mapped[list[AttendanceRecord]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    images: Mapped[list[AttendanceSessionImage]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class AttendanceSessionImage(Base):
    """Classroom photo attached to a session (evidence now; Phase 6 recognition input).
    Files live in uploads/attendance/<session_id>/; only metadata is stored here."""

    __tablename__ = "attendance_session_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"), index=True
    )
    image_path: Mapped[str] = mapped_column(String(500))  # relative to UPLOAD_DIR; never returned
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    file_size: Mapped[int] = mapped_column(Integer)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped[AttendanceSession] = relationship(back_populates="images")


class AttendanceRecord(TimestampMixin, Base):
    """A student's status in one session: the session roster.

    Rows are created when the session starts (a snapshot of active enrollments), so later
    enrollment changes never rewrite a past roster. `status` is NULL ("not marked yet") while
    the session is a draft; finalization requires every row to be marked.

    Duplicate prevention: UNIQUE(session_id, student_id), together with the sessions table's
    one-active-session-per-slot index. Course/section/date/teacher/department are denormalised
    from the session for fast filtering in reports and strict department scoping.
    """

    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("session_id", "student_id"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="RESTRICT"), index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id", ondelete="RESTRICT"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"), index=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id", ondelete="RESTRICT"))
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="RESTRICT"))
    attendance_date: Mapped[date] = mapped_column(Date, index=True)
    attendance_time: Mapped[time | None] = mapped_column(Time)
    session_number: Mapped[int] = mapped_column(SmallInteger, default=1)
    status: Mapped[AttendanceStatus | None] = mapped_column(str_enum(AttendanceStatus), index=True)
    note: Mapped[str | None] = mapped_column(String(200))  # e.g. "Medical leave"
    confidence: Mapped[float | None] = mapped_column(Float)  # 0..1, null for manual
    method: Mapped[AttendanceMethod] = mapped_column(str_enum(AttendanceMethod))
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    last_modified_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Set when face recognition (Phase 6) filled or confirmed this record.
    recognition_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("attendance_recognition_runs.id", ondelete="SET NULL")
    )
    recognition_face_id: Mapped[int | None] = mapped_column(
        ForeignKey("attendance_recognition_faces.id", ondelete="SET NULL")
    )

    session: Mapped[AttendanceSession] = relationship(back_populates="records")
    student: Mapped[Student] = relationship()
    modifications: Mapped[list[AttendanceModification]] = relationship(back_populates="record")


class AttendanceModification(Base):
    """Immutable history of corrections to a finalized attendance record (incl. HOD overrides)."""

    __tablename__ = "attendance_modifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("attendance_records.id", ondelete="CASCADE"), index=True
    )
    modified_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    modifier_role: Mapped[UserRole] = mapped_column(str_enum(UserRole))
    old_value: Mapped[dict[str, Any]] = mapped_column(JSONType)
    new_value: Mapped[dict[str, Any]] = mapped_column(JSONType)
    reason: Mapped[str] = mapped_column(Text)
    modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    record: Mapped[AttendanceRecord] = relationship(back_populates="modifications")



class AttendanceRecognitionRun(Base):
    """One "Run Face Recognition" on a draft session. Counts and settings only — no vectors."""

    __tablename__ = "attendance_recognition_runs"
    __table_args__ = (
        # At most one run in progress per session, enforced by the database: two "Run" clicks
        # (two tabs, a double tap) cannot both start one.
        Index(
            "uq_recognition_runs_one_processing", "session_id", unique=True,
            postgresql_where=text("status = 'processing'"),
            sqlite_where=text("status = 'processing'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[RecognitionRunStatus] = mapped_column(str_enum(RecognitionRunStatus))
    # While processing, the step the server is actually on ("detecting" → "matching" → "saving")
    # and how many photos are done, so the teacher sees real progress. NULL once finished.
    stage: Mapped[str | None] = mapped_column(String(20))
    images_processed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    started_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model_name: Mapped[str] = mapped_column(String(100))
    model_version: Mapped[str] = mapped_column(String(100))
    thresholds: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    faces_detected: Mapped[int] = mapped_column(Integer, default=0)
    confident_count: Mapped[int] = mapped_column(Integer, default=0)
    low_confidence_count: Mapped[int] = mapped_column(Integer, default=0)
    ambiguous_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    unknown_count: Mapped[int] = mapped_column(Integer, default=0)
    students_recognized: Mapped[int] = mapped_column(Integer, default=0)
    roster_size: Mapped[int] = mapped_column(Integer, default=0)
    eligible_count: Mapped[int] = mapped_column(Integer, default=0)  # roster students with embeddings
    applied_count: Mapped[int] = mapped_column(Integer, default=0)  # records pre-filled Present
    preserved_count: Mapped[int] = mapped_column(Integer, default=0)  # teacher decisions kept
    missing_student_ids: Mapped[list[int] | None] = mapped_column(JSONType)  # roster without embeddings
    warnings: Mapped[list[str] | None] = mapped_column(JSONType)
    # Non-sensitive run metadata: model/detector actually used (incl. fallback), detection passes,
    # merged duplicate boxes and timings. Never vectors, pixels or file paths.
    diagnostics: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    error_message: Mapped[str | None] = mapped_column(String(300))

    faces: Mapped[list[AttendanceRecognitionFace]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class AttendanceRecognitionFace(Base):
    """A face detected in a classroom photo during a run: box, suggestion, teacher decision.
    The face pixels and embedding are never stored."""

    __tablename__ = "attendance_recognition_faces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("attendance_recognition_runs.id", ondelete="CASCADE"), index=True
    )
    image_id: Mapped[int] = mapped_column(
        ForeignKey("attendance_session_images.id", ondelete="CASCADE"), index=True
    )
    face_index: Mapped[int] = mapped_column(Integer)
    bbox_x: Mapped[int] = mapped_column(Integer)
    bbox_y: Mapped[int] = mapped_column(Integer)
    bbox_w: Mapped[int] = mapped_column(Integer)
    bbox_h: Mapped[int] = mapped_column(Integer)
    det_score: Mapped[float] = mapped_column(Float)
    category: Mapped[RecognitionCategory] = mapped_column(str_enum(RecognitionCategory))
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id", ondelete="SET NULL"))  # suggestion
    similarity: Mapped[float | None] = mapped_column(Float)
    second_student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id", ondelete="SET NULL"))
    second_similarity: Mapped[float | None] = mapped_column(Float)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    decision: Mapped[FaceDecision] = mapped_column(str_enum(FaceDecision))
    assigned_student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id", ondelete="SET NULL"))
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[AttendanceRecognitionRun] = relationship(back_populates="faces")
