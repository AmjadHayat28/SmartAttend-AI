"""Teacher ↔ course/section assignments and student ↔ course enrollments."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.academic import Course, Section, Semester
    from backend.app.models.people import Student, Teacher


class TeacherCourseAssignment(TimestampMixin, Base):
    """A teacher teaching a course to a section (a "class offering").

    This row is the authorisation boundary for teachers: a teacher may only see
    sections/courses/students reachable through an active assignment.
    """

    __tablename__ = "teacher_course_assignments"
    __table_args__ = (UniqueConstraint("teacher_id", "course_id", "section_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"), index=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("sections.id", ondelete="RESTRICT"), index=True
    )
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id", ondelete="RESTRICT"))
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    assigned_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    teacher: Mapped[Teacher] = relationship(back_populates="assignments")
    course: Mapped[Course] = relationship()
    section: Mapped[Section] = relationship()
    semester: Mapped[Semester] = relationship()


class StudentCourseEnrollment(TimestampMixin, Base):
    """Which courses a student takes in a given semester/section.

    Recognition candidates for a session = active enrollments for (course, section).
    """

    __tablename__ = "student_course_enrollments"
    __table_args__ = (UniqueConstraint("student_id", "course_id", "semester_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"), index=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("sections.id", ondelete="RESTRICT"), index=True
    )
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id", ondelete="RESTRICT"))
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    student: Mapped[Student] = relationship(back_populates="enrollments")
    course: Mapped[Course] = relationship()
    section: Mapped[Section] = relationship()
