"""Role profiles linked 1:1 to users."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, text, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database.base import Base, TimestampMixin
from backend.app.models.enums import FaceEnrollmentStatus, str_enum

if TYPE_CHECKING:
    from backend.app.models.academic import Batch, Department, Section, Semester
    from backend.app.models.assignments import StudentCourseEnrollment, TeacherCourseAssignment
    from backend.app.models.face import FaceEmbedding, StudentFaceImage
    from backend.app.models.user import User


class Hod(TimestampMixin, Base):
    """Head of Department.

    UNIQUE(user_id): a HOD belongs to exactly one department.
    Partial UNIQUE(department_id) WHERE is_current: at most one current HOD per department,
    while former HODs keep their row (is_current = false) as history after a replacement.
    """

    __tablename__ = "hods"
    __table_args__ = (
        Index(
            "uq_hods_current_department",
            "department_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    employee_id: Mapped[str] = mapped_column(String(50), unique=True)
    phone: Mapped[str | None] = mapped_column(String(30))
    appointed_on: Mapped[date | None] = mapped_column(Date)

    user: Mapped[User] = relationship(back_populates="hod_profile")
    department: Mapped[Department] = relationship(back_populates="hods")


class Teacher(TimestampMixin, Base):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    employee_id: Mapped[str] = mapped_column(String(50), unique=True)
    designation: Mapped[str | None] = mapped_column(String(100))  # e.g. "Lecturer"
    phone: Mapped[str | None] = mapped_column(String(30))

    user: Mapped[User] = relationship(back_populates="teacher_profile")
    department: Mapped[Department] = relationship(back_populates="teachers")
    assignments: Mapped[list[TeacherCourseAssignment]] = relationship(back_populates="teacher")


class Student(TimestampMixin, Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="RESTRICT"), index=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="RESTRICT"), index=True
    )
    section_id: Mapped[int] = mapped_column(
        ForeignKey("sections.id", ondelete="RESTRICT"), index=True
    )
    registration_no: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    profile_photo_path: Mapped[str | None] = mapped_column(String(500))  # relative to UPLOAD_DIR
    profile_photo_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Face enrollment is reviewed separately from account approval (users.status).
    face_enrollment_status: Mapped[FaceEnrollmentStatus] = mapped_column(
        str_enum(FaceEnrollmentStatus),
        default=FaceEnrollmentStatus.NOT_STARTED,
        server_default=FaceEnrollmentStatus.NOT_STARTED.value,
        index=True,
    )
    face_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    face_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    face_reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    face_review_note: Mapped[str | None] = mapped_column(Text)  # rejection reason shown to the student

    user: Mapped[User] = relationship(back_populates="student_profile", foreign_keys=[user_id])
    department: Mapped[Department] = relationship(back_populates="students")
    batch: Mapped[Batch] = relationship()
    semester: Mapped[Semester] = relationship()
    section: Mapped[Section] = relationship(back_populates="students")
    enrollments: Mapped[list[StudentCourseEnrollment]] = relationship(back_populates="student")
    face_images: Mapped[list[StudentFaceImage]] = relationship(back_populates="student")
    face_embeddings: Mapped[list[FaceEmbedding]] = relationship(back_populates="student")
