"""System-wide audit trail."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database.base import Base
from backend.app.models.attendance import JSONType


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # Department the action belongs to, so HODs can view their department's audit trail.
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(100), index=True)  # e.g. "student.approved"
    entity: Mapped[str] = mapped_column(String(100))  # e.g. "student"
    entity_id: Mapped[str | None] = mapped_column(String(64))
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class LoginAttempt(Base):
    """One failed login, for the shared (multi-worker) login rate limiter. Only a SHA-256 of
    "ip:email" is stored; rows older than the rate-limit window are deleted automatically."""

    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), index=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
