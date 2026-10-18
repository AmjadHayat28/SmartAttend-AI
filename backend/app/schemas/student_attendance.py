"""Student "My Attendance": the signed-in student's own records only.

Deliberately minimal — no photos, recognition confidence/results, notes, audit data or
other students' information.
"""

from datetime import date

from pydantic import BaseModel

from backend.app.models.enums import AttendanceStatus


class AttendancePolicyOut(BaseModel):
    late_weight: float
    excused_policy: str


class StudentSubjectSummary(BaseModel):
    course_id: int
    course_code: str
    course_title: str
    section_name: str
    teacher_names: list[str]
    total_classes: int  # finalized sessions the student was marked in
    present: int
    absent: int
    late: int
    excused: int
    attended: float
    conducted: int
    percentage: float | None  # None when no finalized classes yet
    low_attendance: bool


class StudentAttendanceOverview(BaseModel):
    threshold: float
    policy: AttendancePolicyOut
    subjects: list[StudentSubjectSummary]


class StudentAttendanceEntry(BaseModel):
    session_date: date
    session_number: int
    status: AttendanceStatus


class StudentSubjectDetail(BaseModel):
    threshold: float
    subject: StudentSubjectSummary
    records: list[StudentAttendanceEntry]  # newest first
