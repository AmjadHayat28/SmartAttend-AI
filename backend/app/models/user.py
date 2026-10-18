from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database.base import Base, TimestampMixin
from backend.app.models.enums import AccountStatus, UserRole, str_enum

if TYPE_CHECKING:
    from backend.app.models.people import Hod, Student, Teacher


class User(TimestampMixin, Base):
    """Login identity. Role-specific data lives in hods / teachers / students."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(150))
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole), index=True)
    status: Mapped[AccountStatus] = mapped_column(
        str_enum(AccountStatus), default=AccountStatus.PENDING, index=True
    )
    status_reason: Mapped[str | None] = mapped_column(String(500))
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Bumped on password change / suspension so previously issued tokens are rejected.
    token_version: Mapped[int] = mapped_column(Integer, default=0)

    hod_profile: Mapped[Hod | None] = relationship(back_populates="user", uselist=False)
    teacher_profile: Mapped[Teacher | None] = relationship(back_populates="user", uselist=False)
    student_profile: Mapped[Student | None] = relationship(
        back_populates="user", uselist=False, foreign_keys="Student.user_id"
    )

    @property
    def department_id(self) -> int | None:
        """Department this account is scoped to (None for super admin)."""
        profile = self.hod_profile or self.teacher_profile or self.student_profile
        return profile.department_id if profile else None

    @property
    def is_active(self) -> bool:
        return self.status == AccountStatus.ACTIVE

    def __repr__(self) -> str:
        return f"<User {self.id} {self.email} {self.role.value}>"
