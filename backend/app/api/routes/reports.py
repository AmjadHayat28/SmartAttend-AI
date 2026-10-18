"""Teacher attendance reports and Excel export — the caller's own ACTIVE classes only.

Teachers only: HODs, the super admin and students get 403. Another teacher's (or a removed)
assignment is 404. FINALIZED sessions only; percentages follow the shared attendance policy.
"""

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response, status

from backend.app.auth.dependencies import DbSession, TeacherUser
from backend.app.schemas.assignments import AssignmentOut
from backend.app.schemas.reports import ClassReport, DailyReport, StudentReport
from backend.app.services import enrollment_service, report_excel
from backend.app.services import report_service as svc

router = APIRouter(prefix="/reports", tags=["reports"])

Year = Query(ge=2000, le=2100)
Month = Query(ge=1, le=12)


@router.get("/classes", response_model=list[AssignmentOut])
def report_classes(user: TeacherUser, db: DbSession):
    """The caller's active class assignments available for reports."""
    return enrollment_service.list_teacher_classes(db, user)


@router.get("/class/{assignment_id}", response_model=ClassReport)
def class_summary(assignment_id: int, user: TeacherUser, db: DbSession, date_from: date | None = None,
                  date_to: date | None = None, q: str | None = Query(None, max_length=100)):
    """Per-student totals over the class's finalized sessions, optionally within a date range."""
    return svc.class_report(db, user, assignment_id, date_from=date_from, date_to=date_to, q=q)


@router.get("/class/{assignment_id}/daily", response_model=DailyReport)
def daily(assignment_id: int, user: TeacherUser, db: DbSession, report_date: date = Query(alias="date"),
          q: str | None = Query(None, max_length=100)):
    """Every finalized session of the class on one date, with each student's status."""
    return svc.daily_report(db, user, assignment_id, report_date, q=q)


@router.get("/class/{assignment_id}/monthly", response_model=ClassReport)
def monthly(assignment_id: int, user: TeacherUser, db: DbSession, year: int = Year, month: int = Month,
            q: str | None = Query(None, max_length=100)):
    """Per-student totals over the finalized sessions of one calendar month."""
    return svc.monthly_report(db, user, assignment_id, year, month, q=q)


@router.get("/class/{assignment_id}/students/{student_id}", response_model=StudentReport)
def student(assignment_id: int, student_id: int, user: TeacherUser, db: DbSession,
            date_from: date | None = None, date_to: date | None = None):
    """One student of the class: totals plus date-wise history (newest first)."""
    return svc.student_report(db, user, assignment_id, student_id, date_from=date_from, date_to=date_to)


def _need(value, name: str):
    if value is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'{name}' is required for this report type")
    return value


@router.get("/class/{assignment_id}/export", response_class=Response,
            responses={200: {"content": {report_excel.XLSX_MEDIA_TYPE: {}}}})
def export(assignment_id: int, user: TeacherUser, db: DbSession,
           report_type: Literal["summary", "daily", "monthly", "student"] = Query("summary", alias="type"),
           report_date: date | None = Query(None, alias="date"), date_from: date | None = None,
           date_to: date | None = None, year: int | None = Query(None, ge=2000, le=2100),
           month: int | None = Query(None, ge=1, le=12), student_id: int | None = None,
           q: str | None = Query(None, max_length=100)):
    """Download a report as a real .xlsx workbook.

    type=summary [&date_from&date_to] | type=daily&date=YYYY-MM-DD | type=monthly&year&month |
    type=student&student_id [&date_from&date_to]
    """
    if report_type == "summary":
        report = svc.class_report(db, user, assignment_id, date_from=date_from, date_to=date_to, q=q)
        parts = ["Attendance_Summary"] if not (date_from or date_to) else [
            str(date_from or ""), "to" if date_from and date_to else "", str(date_to or ""), "Attendance_Summary"]
        content = report_excel.class_workbook(report, "Class Attendance Summary", "Summary")
    elif report_type == "daily":
        day = _need(report_date, "date")
        report = svc.daily_report(db, user, assignment_id, day, q=q)
        parts = [day.isoformat(), "Attendance"]
        content = report_excel.daily_workbook(report)
    elif report_type == "monthly":
        y, m = _need(year, "year"), _need(month, "month")
        report = svc.monthly_report(db, user, assignment_id, y, m, q=q)
        parts = [f"{y:04d}-{m:02d}", "Attendance"]
        content = report_excel.class_workbook(report, "Monthly Attendance Report", "Monthly",
                                              period=f"{y:04d}-{m:02d}")
    else:
        sid = _need(student_id, "student_id")
        report = svc.student_report(db, user, assignment_id, sid, date_from=date_from, date_to=date_to)
        parts = [report.student.registration_no, "Attendance"]
        content = report_excel.student_workbook(report)
    name = report_excel.filename(report.report_class, *parts)
    return Response(content, media_type=report_excel.XLSX_MEDIA_TYPE,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
