"""Seed demo data for local development (idempotent).

Run with:  uv run python -m backend.app.scripts.seed_demo

Creates two departments (to exercise isolation), a HOD, a teacher with an assignment,
an approved student with enrollments, and a pending student awaiting approval.
All demo passwords: Demo@1234
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth.security import hash_password
from backend.app.database.init_db import seed_super_admin, upgrade_database
from backend.app.database.session import SessionLocal
from backend.app.models import (
    AccountStatus,
    Batch,
    Course,
    Department,
    Hod,
    Section,
    Semester,
    Student,
    StudentCourseEnrollment,
    Teacher,
    TeacherCourseAssignment,
    User,
    UserRole,
)

DEMO_PASSWORD = "Demo@1234"


def _get_or_create(db: Session, model, defaults: dict | None = None, **lookup):
    obj = db.scalar(select(model).filter_by(**lookup))
    if obj is None:
        obj = model(**lookup, **(defaults or {}))
        db.add(obj)
        db.flush()
    return obj


def _user(db: Session, email: str, name: str, role: UserRole, status=AccountStatus.ACTIVE) -> User:
    return _get_or_create(
        db, User, email=email,
        defaults={"full_name": name, "role": role, "status": status,
                  "password_hash": hash_password(DEMO_PASSWORD)},
    )


def seed(db: Session) -> None:
    cse = _get_or_create(db, Department, code="CSE", defaults={"name": "Computer Systems Engineering"})
    _get_or_create(db, Department, code="EE", defaults={"name": "Electrical Engineering"})

    batch = _get_or_create(db, Batch, department_id=cse.id, name="F23", defaults={"start_year": 2023, "end_year": 2027})
    sem6 = _get_or_create(db, Semester, batch_id=batch.id, number=6,
                          defaults={"department_id": cse.id, "name": "Semester 6", "is_current": True,
                                    "start_date": date(2026, 2, 1), "end_date": date(2026, 6, 30)})
    sec_a = _get_or_create(db, Section, semester_id=sem6.id, name="A", defaults={"department_id": cse.id, "capacity": 50})
    _get_or_create(db, Section, semester_id=sem6.id, name="B", defaults={"department_id": cse.id, "capacity": 50})

    courses = [
        _get_or_create(db, Course, department_id=cse.id, code=code,
                       defaults={"title": title, "is_lab": lab, "semester_number": 6, "credit_hours": 1 if lab else 3})
        for code, title, lab in [
            ("CS-321", "Digital System Design", False),
            ("CS-321L", "Digital System Design Lab", True),
            ("MA-301", "Numerical Analysis", False),
            ("CS-341", "Parallel and Distributed Computing", False),
        ]
    ]

    hod_user = _user(db, "hod.cse@smartclass.edu", "Dr. Ayesha Khan", UserRole.HOD)
    _get_or_create(db, Hod, user_id=hod_user.id, defaults={"department_id": cse.id, "employee_id": "EMP-HOD-001"})

    teacher_user = _user(db, "teacher.cse@smartclass.edu", "Engr. Bilal Ahmed", UserRole.TEACHER)
    teacher = _get_or_create(db, Teacher, user_id=teacher_user.id,
                             defaults={"department_id": cse.id, "employee_id": "EMP-T-101", "designation": "Lecturer"})
    for course in courses[:2]:
        _get_or_create(db, TeacherCourseAssignment, teacher_id=teacher.id, course_id=course.id, section_id=sec_a.id,
                       defaults={"semester_id": sem6.id, "department_id": cse.id})

    student_user = _user(db, "student.cse@smartclass.edu", "Ali Raza", UserRole.STUDENT)
    student = _get_or_create(db, Student, user_id=student_user.id,
                             defaults={"department_id": cse.id, "batch_id": batch.id, "semester_id": sem6.id,
                                       "section_id": sec_a.id, "registration_no": "F23CSE01"})
    for course in courses:
        _get_or_create(db, StudentCourseEnrollment, student_id=student.id, course_id=course.id, semester_id=sem6.id,
                       defaults={"section_id": sec_a.id, "department_id": cse.id})

    pending_user = _user(db, "pending.cse@smartclass.edu", "Sara Malik", UserRole.STUDENT, AccountStatus.PENDING)
    _get_or_create(db, Student, user_id=pending_user.id,
                   defaults={"department_id": cse.id, "batch_id": batch.id, "semester_id": sem6.id,
                             "section_id": sec_a.id, "registration_no": "F23CSE03"})
    db.commit()


def main() -> None:
    upgrade_database()
    seed_super_admin()
    with SessionLocal() as db:
        seed(db)
    print("Demo data ready. Password for all demo accounts:", DEMO_PASSWORD)


if __name__ == "__main__":
    main()
