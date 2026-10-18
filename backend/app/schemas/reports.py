"""Teacher attendance reports (own active classes only). FINALIZED sessions only; every
percentage and low-attendance flag comes from services/attendance_policy.py.

Never contains photos, recognition data, notes or audit internals.
"""

from datetime import date

from pydantic import BaseModel

from backend.app.models.enums import AttendanceStatus


class ReportClass(BaseModel):
    assignment_id: int
    course_id: int
    course_code: str
    course_title: str
    section_id: int
    section_name: str
    semester_number: int
    batch_name: str
    teacher_name: str


class Counts(BaseModel):
    total_classes: int  # finalized classes the student was marked in
    present: int
    absent: int
    late: int
    excused: int
    attended: float
    conducted: int
    percentage: float | None  # None when there is nothing to count
    low_attendance: bool


class StudentReportRow(Counts):
    student_id: int
    registration_no: str
    student_name: str
    currently_enrolled: bool  # False: kept for history after being unenrolled


class ClassReport(BaseModel):
    """Class summary (optionally over a date range) and the monthly report share this shape."""

    report_class: ReportClass
    threshold: float
    date_from: date | None
    date_to: date | None
    finalized_sessions: int
    enrolled_students: int
    class_percentage: float | None  # all students' finalized records under the same policy
    low_attendance_students: int
    students: list[StudentReportRow]


class DailyRecord(BaseModel):
    student_id: int
    registration_no: str
    student_name: str
    status: AttendanceStatus


class DailySession(BaseModel):
    session_number: int
    present: int
    absent: int
    late: int
    excused: int
    percentage: float | None
    records: list[DailyRecord]


class DailyReport(BaseModel):
    report_class: ReportClass
    report_date: date
    sessions: list[DailySession]  # by session number


class StudentHistoryEntry(BaseModel):
    session_date: date
    session_number: int
    status: AttendanceStatus


class StudentReport(BaseModel):
    report_class: ReportClass
    threshold: float
    date_from: date | None
    date_to: date | None
    student: StudentReportRow
    records: list[StudentHistoryEntry]  # newest first
