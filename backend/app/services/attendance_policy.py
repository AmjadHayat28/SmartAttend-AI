"""Attendance-percentage policy — one place, so every screen and report agrees.

Only FINALIZED sessions count. Configuration (see .env.example):

    attended  = present + late × ATTENDANCE_LATE_WEIGHT  (+ excused when policy = "present")
    conducted = all marked records                        (− excused when policy = "exclude")
    percentage = attended / conducted × 100               (None when nothing was conducted)

Late is still reported separately even when it counts fully toward attendance.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models import AttendanceRecord, AttendanceSession, AttendanceStatus, SessionStatus


@dataclass(frozen=True)
class AttendanceSummary:
    present: int = 0
    absent: int = 0
    late: int = 0
    excused: int = 0

    @property
    def total(self) -> int:
        return self.present + self.absent + self.late + self.excused

    @property
    def attended(self) -> float:
        value = self.present + self.late * settings.ATTENDANCE_LATE_WEIGHT
        if settings.ATTENDANCE_EXCUSED_POLICY == "present":
            value += self.excused
        return value

    @property
    def conducted(self) -> int:
        return self.total - self.excused if settings.ATTENDANCE_EXCUSED_POLICY == "exclude" else self.total

    @property
    def percentage(self) -> float | None:
        return round(100 * self.attended / self.conducted, 1) if self.conducted else None

    @property
    def is_low(self) -> bool:
        pct = self.percentage
        return pct is not None and pct < settings.LOW_ATTENDANCE_THRESHOLD


def summarize(counts: Mapping[AttendanceStatus | str | None, int]) -> AttendanceSummary:
    """Build a summary from {status: count}; unmarked (None) rows are ignored."""
    def get(status: AttendanceStatus) -> int:
        return int(counts.get(status, 0) or counts.get(status.value, 0) or 0)

    return AttendanceSummary(present=get(AttendanceStatus.PRESENT), absent=get(AttendanceStatus.ABSENT),
                             late=get(AttendanceStatus.LATE), excused=get(AttendanceStatus.EXCUSED))


def finalized_counts(db: Session, *filters, group_by: Iterable = ()) -> dict:
    """{(group values…): {status: count}} over finalized sessions only."""
    group_cols = list(group_by)
    stmt = (
        select(*group_cols, AttendanceRecord.status, func.count(AttendanceRecord.id))
        .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
        .where(AttendanceSession.status == SessionStatus.FINALIZED, AttendanceRecord.status.is_not(None), *filters)
        .group_by(*group_cols, AttendanceRecord.status)
    )
    result: dict = {}
    for row in db.execute(stmt).all():
        key = tuple(row[: len(group_cols)])
        result.setdefault(key, {})[row[-2]] = row[-1]
    return result


def policy_description() -> dict:
    return {
        "late_weight": settings.ATTENDANCE_LATE_WEIGHT,
        "excused_policy": settings.ATTENDANCE_EXCUSED_POLICY,
        "low_threshold": settings.LOW_ATTENDANCE_THRESHOLD,
    }
