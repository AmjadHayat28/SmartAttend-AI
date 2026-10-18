"""Importing this package registers every model on Base.metadata."""

from backend.app.models.academic import Batch, Course, Department, Section, Semester
from backend.app.models.assignments import StudentCourseEnrollment, TeacherCourseAssignment
from backend.app.models.attendance import (
    AttendanceModification,
    AttendanceRecord,
    AttendanceRecognitionFace,
    AttendanceRecognitionRun,
    AttendanceSession,
    AttendanceSessionImage,
)
from backend.app.models.audit import AuditLog, LoginAttempt
from backend.app.models.enums import (
    AccountStatus,
    AttendanceMethod,
    AttendanceStatus,
    FaceDecision,
    FaceEnrollmentStatus,
    FaceImageType,
    ImageCheckStatus,
    RecognitionCategory,
    RecognitionRunStatus,
    SessionStatus,
    UserRole,
)
from backend.app.models.face import FaceEmbedding, StudentFaceImage
from backend.app.models.people import Hod, Student, Teacher
from backend.app.models.user import User

__all__ = [
    "AccountStatus",
    "AttendanceMethod",
    "AttendanceModification",
    "AttendanceRecord",
    "AttendanceRecognitionFace",
    "AttendanceRecognitionRun",
    "AttendanceSession",
    "AttendanceSessionImage",
    "AttendanceStatus",
    "AuditLog",
    "Batch",
    "Course",
    "Department",
    "FaceDecision",
    "FaceEmbedding",
    "FaceEnrollmentStatus",
    "FaceImageType",
    "Hod",
    "ImageCheckStatus",
    "LoginAttempt",
    "RecognitionCategory",
    "RecognitionRunStatus",
    "Section",
    "Semester",
    "SessionStatus",
    "Student",
    "StudentCourseEnrollment",
    "StudentFaceImage",
    "Teacher",
    "TeacherCourseAssignment",
    "User",
    "UserRole",
]
