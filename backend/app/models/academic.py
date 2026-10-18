"""Academic structure: Department → Batch → Semester → Section, plus Courses."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.people import Hod, Student, Teacher


class Department(TimestampMixin, Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # e.g. "CSE"
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    hods: Mapped[list[Hod]] = relationship(back_populates="department")
    teachers: Mapped[list[Teacher]] = relationship(back_populates="department")
    students: Mapped[list[Student]] = relationship(back_populates="department")
    batches: Mapped[list[Batch]] = relationship(back_populates="department")
    courses: Mapped[list[Course]] = relationship(back_populates="department")


class Batch(TimestampMixin, Base):
    """Intake cohort, e.g. "F23" (Fall 2023) of a department."""

    __tablename__ = "batches"
    __table_args__ = (
        UniqueConstraint("department_id", "name"),
        CheckConstraint("end_year IS NULL OR end_year >= start_year", name="year_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(50))
    start_year: Mapped[int] = mapped_column(SmallInteger)
    end_year: Mapped[int | None] = mapped_column(SmallInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    department: Mapped[Department] = relationship(back_populates="batches")
    semesters: Mapped[list[Semester]] = relationship(back_populates="batch")


class Semester(TimestampMixin, Base):
    """A term of a batch, e.g. Semester 6 of F23."""

    __tablename__ = "semesters"
    __table_args__ = (
        UniqueConstraint("batch_id", "number"),
        CheckConstraint("number BETWEEN 1 AND 12", name="number_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="RESTRICT"), index=True)
    # Denormalised from batch so department scoping never needs a join chain.
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    number: Mapped[int] = mapped_column(SmallInteger)
    # e.g. "Semester 6" or "Spring 2026"; defaults to "Semester <number>" (same rule as migration 0002).
    name: Mapped[str] = mapped_column(
        String(50), default=lambda ctx: f"Semester {ctx.get_current_parameters()['number']}"
    )
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    batch: Mapped[Batch] = relationship(back_populates="semesters")
    sections: Mapped[list[Section]] = relationship(back_populates="semester")


class Section(TimestampMixin, Base):
    """A class group, e.g. Section A of F23 / Semester 6. "Class" in the UI = section."""

    __tablename__ = "sections"
    __table_args__ = (UniqueConstraint("semester_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="RESTRICT"), index=True
    )
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(20))
    capacity: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    semester: Mapped[Semester] = relationship(back_populates="sections")
    students: Mapped[list[Student]] = relationship(back_populates="section")


class Course(TimestampMixin, Base):
    """Department course catalogue entry (subject)."""

    __tablename__ = "courses"
    __table_args__ = (
        UniqueConstraint("department_id", "code"),
        CheckConstraint("credit_hours >= 0", name="credit_hours_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    code: Mapped[str] = mapped_column(String(20))  # e.g. "CS-312"
    title: Mapped[str] = mapped_column(String(200))  # e.g. "Digital System Design"
    credit_hours: Mapped[int] = mapped_column(SmallInteger, default=3)
    is_lab: Mapped[bool] = mapped_column(Boolean, default=False)
    semester_number: Mapped[int | None] = mapped_column(SmallInteger)  # suggested semester
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    department: Mapped[Department] = relationship(back_populates="courses")
