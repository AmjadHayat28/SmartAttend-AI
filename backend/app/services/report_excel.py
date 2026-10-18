"""Real .xlsx workbooks (openpyxl) for teacher attendance reports.

Each sheet: a title block (system, report, course, section, teacher, period, threshold,
generated-at), then a bold, frozen table header and the rows. Percentages are written as
numbers with a % format (never re-calculated here — they come from the report service).
Never includes photos, recognition data, notes or audit internals.
"""

import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from backend.app.core.config import settings
from backend.app.schemas.reports import ClassReport, DailyReport, ReportClass, StudentReport, StudentReportRow

SYSTEM_TITLE = "SmartClass AI Attendance Management System"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_HEADER_FILL = PatternFill("solid", fgColor="1E3A8A")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_LOW_FONT = Font(bold=True, color="B91C1C")
_THIN = Side(style="thin", color="CBD5E1")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

SUMMARY_HEADERS = ["Registration Number", "Student Name", "Total Classes", "Present", "Absent", "Late",
                   "Excused", "Attendance %", "Low Attendance", "Currently Enrolled"]
DAILY_HEADERS = ["Registration Number", "Student Name", "Date", "Session Number", "Status"]
HISTORY_HEADERS = ["Date", "Session Number", "Status"]



def _generated_at(now: datetime | None = None) -> str:
    """When the file was made, in the institution's timezone (APP_TIMEZONE), with the zone named."""
    now = now or datetime.now(timezone.utc)
    if settings.APP_TIMEZONE:
        local = now.astimezone(ZoneInfo(settings.APP_TIMEZONE))
        return f"{local:%Y-%m-%d %H:%M} ({settings.APP_TIMEZONE}, UTC{local:%z})"
    return f"{now:%Y-%m-%d %H:%M} UTC"

def _safe(part: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", part.replace(" ", ""))


def filename(cls: ReportClass, *parts: str) -> str:
    """e.g. CS321_SectionA_2026-10_Attendance.xlsx — letters, digits, dash and underscore only."""
    code = re.sub(r"[^A-Za-z0-9]", "", cls.course_code) or "Course"
    pieces = [code, f"Section{_safe(cls.section_name)}", *(_safe(p) for p in parts if p)]
    return "_".join(p for p in pieces if p) + ".xlsx"


def _title_block(ws: Worksheet, title: str, cls: ReportClass, period: str, threshold: float | None,
                 extra: list[tuple[str, str]] = ()) -> int:
    ws["A1"] = SYSTEM_TITLE
    ws["A1"].font = Font(bold=True, size=14, color="1E3A8A")
    ws["A2"] = title
    ws["A2"].font = Font(bold=True, size=12)
    info = [
        ("Course", f"{cls.course_code} — {cls.course_title}"),
        ("Section", f"{cls.batch_name} · Semester {cls.semester_number} · Section {cls.section_name}"),
        ("Teacher", cls.teacher_name),
        ("Period", period),
        *extra,
    ]
    if threshold is not None:
        info.append(("Low attendance below", f"{threshold:g}%"))
    info.append(("Generated", _generated_at()))
    row = 4
    for label, value in info:
        ws.cell(row=row, column=1, value=label).font = Font(bold=True, color="475569")
        ws.cell(row=row, column=2, value=value)
        row += 1
    return row + 1  # one blank row before the table


def _header(ws: Worksheet, row: int, headers: list[str]) -> None:
    for col, text in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=col, value=text)
        cell.font, cell.fill, cell.border = _HEADER_FONT, _HEADER_FILL, _BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _pct_cell(ws: Worksheet, row: int, col: int, pct: float | None) -> None:
    cell = ws.cell(row=row, column=col)
    if pct is None:
        cell.value = "N/A"
        cell.alignment = Alignment(horizontal="right")
    else:
        cell.value = pct / 100
        cell.number_format = "0.0%"


def _student_row(ws: Worksheet, row: int, r: StudentReportRow) -> None:
    values = [r.registration_no, r.student_name, r.total_classes, r.present, r.absent, r.late, r.excused]
    for col, value in enumerate(values, start=1):
        ws.cell(row=row, column=col, value=value)
    _pct_cell(ws, row, 8, r.percentage)
    low = ws.cell(row=row, column=9, value="Low Attendance" if r.low_attendance else "")
    if r.low_attendance:
        low.font = _LOW_FONT
        ws.cell(row=row, column=8).font = _LOW_FONT
    ws.cell(row=row, column=10, value="Yes" if r.currently_enrolled else "No")
    for col in range(1, 11):
        ws.cell(row=row, column=col).border = _BORDER


def _widths(ws: Worksheet, minimum: int = 10, maximum: int = 42, skip_rows: int = 0) -> None:
    widths: dict[int, int] = {}
    for row in ws.iter_rows(min_row=skip_rows + 1):
        for cell in row:
            if cell.value is None:
                continue
            text = cell.value.strftime("%Y-%m-%d") if isinstance(cell.value, date) else str(cell.value)
            widths[cell.column] = max(widths.get(cell.column, 0), len(text) + 2)
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = max(minimum, min(maximum, width))
    ws.column_dimensions["A"].width = max(ws.column_dimensions["A"].width or 0, 22)


def _save(wb: Workbook) -> bytes:
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _period(date_from: date | None, date_to: date | None) -> str:
    if date_from and date_to:
        return f"{date_from.isoformat()} to {date_to.isoformat()}"
    if date_from:
        return f"From {date_from.isoformat()}"
    if date_to:
        return f"Up to {date_to.isoformat()}"
    return "All finalized classes"


def class_workbook(report: ClassReport, title: str, sheet: str, period: str | None = None) -> bytes:
    """Class summary or monthly report: one row per student."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    row = _title_block(ws, title, report.report_class, period or _period(report.date_from, report.date_to),
                       report.threshold, [
                           ("Finalized sessions", str(report.finalized_sessions)),
                           ("Enrolled students", str(report.enrolled_students)),
                           ("Class attendance", "N/A" if report.class_percentage is None
                            else f"{report.class_percentage:g}%"),
                       ])
    _header(ws, row, SUMMARY_HEADERS)
    ws.freeze_panes = ws.cell(row=row + 1, column=1)
    for i, r in enumerate(report.students, start=row + 1):
        _student_row(ws, i, r)
    if report.students:
        ws.auto_filter.ref = f"A{row}:{get_column_letter(len(SUMMARY_HEADERS))}{row + len(report.students)}"
    _widths(ws, skip_rows=row - 1)
    return _save(wb)


def daily_workbook(report: DailyReport) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Daily"
    row = _title_block(ws, "Daily Attendance Report", report.report_class, report.report_date.isoformat(), None,
                       [("Finalized sessions", str(len(report.sessions)))])
    _header(ws, row, DAILY_HEADERS)
    ws.freeze_panes = ws.cell(row=row + 1, column=1)
    r = row + 1
    for session in report.sessions:
        for rec in session.records:
            values = [rec.registration_no, rec.student_name, report.report_date, session.session_number,
                      rec.status.value.capitalize()]
            for col, value in enumerate(values, start=1):
                cell = ws.cell(row=r, column=col, value=value)
                cell.border = _BORDER
            ws.cell(row=r, column=3).number_format = "yyyy-mm-dd"
            r += 1
    _widths(ws, skip_rows=row - 1)
    return _save(wb)


def student_workbook(report: StudentReport) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Student"
    s = report.student
    row = _title_block(ws, "Student Attendance Report", report.report_class,
                       _period(report.date_from, report.date_to), report.threshold,
                       [("Student", f"{s.student_name} ({s.registration_no})")])
    _header(ws, row, SUMMARY_HEADERS)
    _student_row(ws, row + 1, s)
    row += 3
    ws.cell(row=row, column=1, value="Date-wise history (newest first)").font = Font(bold=True, size=12)
    row += 1
    _header(ws, row, HISTORY_HEADERS)
    for i, rec in enumerate(report.records, start=row + 1):
        ws.cell(row=i, column=1, value=rec.session_date).number_format = "yyyy-mm-dd"
        ws.cell(row=i, column=2, value=rec.session_number)
        ws.cell(row=i, column=3, value=rec.status.value.capitalize())
        for col in range(1, 4):
            ws.cell(row=i, column=col).border = _BORDER
    _widths(ws, skip_rows=row - 5)  # from the summary table header down (skip the title block)
    return _save(wb)
