"""Role-based and department-based authorisation."""

from sqlalchemy import select

from backend.app.models import AccountStatus, Batch, Department, Hod, Section, Semester, Student, User, UserRole
from backend.app.scripts.seed_demo import DEMO_PASSWORD
from tests.conftest import ADMIN_EMAIL

API = "/api/v1"
HOD = "hod.cse@smartclass.edu"
TEACHER = "teacher.cse@smartclass.edu"
STUDENT = "student.cse@smartclass.edu"


def _dept_id(db_session, code: str) -> int:
    with db_session() as db:
        return db.scalar(select(Department.id).where(Department.code == code))


def _user_id(db_session, email: str) -> int:
    with db_session() as db:
        return db.scalar(select(User.id).where(User.email == email))


def test_only_admin_creates_departments(client, login):
    payload = {"name": "Software Engineering", "code": "se"}
    for email in (HOD, TEACHER, STUDENT):
        assert client.post(f"{API}/departments", json=payload, headers=login(email)).status_code == 403
    res = client.post(f"{API}/departments", json=payload, headers=login(ADMIN_EMAIL))
    assert res.status_code == 201
    assert res.json()["code"] == "SE"


def test_hod_sees_only_own_department(client, login, db_session):
    headers = login(HOD)
    listed = client.get(f"{API}/departments", headers=headers).json()
    assert [d["code"] for d in listed] == ["CSE"]
    ee = _dept_id(db_session, "EE")
    assert client.get(f"{API}/departments/{ee}", headers=headers).status_code == 404
    assert len(client.get(f"{API}/departments", headers=login(ADMIN_EMAIL)).json()) == 2


def test_dashboards_are_role_restricted(client, login):
    assert client.get(f"{API}/dashboard/admin", headers=login(HOD)).status_code == 403
    assert client.get(f"{API}/dashboard/hod", headers=login(TEACHER)).status_code == 403
    assert client.get(f"{API}/dashboard/teacher/classes", headers=login(STUDENT)).status_code == 403
    hod = client.get(f"{API}/dashboard/hod", headers=login(HOD)).json()
    assert hod["department_name"] == "Computer Systems Engineering"
    assert hod["pending_approvals"] == 1


def test_teacher_sees_only_assigned_classes(client, login):
    classes = client.get(f"{API}/dashboard/teacher/classes", headers=login(TEACHER)).json()
    assert {c["course_code"] for c in classes} == {"CS-321", "CS-321L"}


def test_student_subject_cards(client, login):
    data = client.get(f"{API}/dashboard/student/subjects", headers=login(STUDENT)).json()
    assert data["threshold"] == 75.0
    assert len(data["subjects"]) == 4
    assert all(s["percentage"] is None for s in data["subjects"])  # no sessions held yet


def test_hod_approves_student_in_own_department(client, login, db_session):
    pending_id = _user_id(db_session, "pending.cse@smartclass.edu")
    headers = login(HOD)
    assert client.get(f"{API}/accounts/pending-students", headers=headers).json()["total"] == 1
    res = client.patch(f"{API}/accounts/{pending_id}/status", json={"status": "active"}, headers=headers)
    assert res.status_code == 200
    login("pending.cse@smartclass.edu")  # can now sign in


def test_hod_cannot_touch_other_department_or_staff(client, login, db_session):
    with db_session() as db:
        ee = db.scalar(select(Department).where(Department.code == "EE"))
        batch = Batch(department_id=ee.id, name="F24", start_year=2024)
        db.add(batch)
        db.flush()
        sem = Semester(batch_id=batch.id, department_id=ee.id, number=1)
        db.add(sem)
        db.flush()
        sec = Section(semester_id=sem.id, department_id=ee.id, name="A")
        db.add(sec)
        db.flush()
        user = User(email="ee.student@test.edu", full_name="EE Student", role=UserRole.STUDENT,
                    status=AccountStatus.PENDING, password_hash="x")
        user.student_profile = Student(department_id=ee.id, batch_id=batch.id, semester_id=sem.id,
                                       section_id=sec.id, registration_no="F24EE01")
        db.add(user)
        db.commit()
        ee_student_id = user.id

    headers = login(HOD)
    # Not visible in the HOD's pending list...
    pending = client.get(f"{API}/accounts/pending-students", headers=headers).json()
    assert all(p["registration_no"] != "F24EE01" for p in pending["items"])
    # ...and cannot be approved (404 hides its existence).
    res = client.patch(f"{API}/accounts/{ee_student_id}/status", json={"status": "active"}, headers=headers)
    assert res.status_code == 404
    # HODs cannot manage accounts above them in the hierarchy. (Phase 3 deliberately lets
    # HODs manage teachers of their own department; see test_people.py for that and for
    # cross-department teacher denial.)
    admin_id = _user_id(db_session, ADMIN_EMAIL)
    res = client.patch(f"{API}/accounts/{admin_id}/status", json={"status": "suspended", "reason": "x"}, headers=headers)
    assert res.status_code == 403
    with db_session() as db:
        other_hod = User(email="hod.other@test.edu", full_name="Other HOD", role=UserRole.HOD,
                         status=AccountStatus.ACTIVE, password_hash="x")
        other_hod.hod_profile = Hod(department_id=ee.id, employee_id="EMP-HOD-EE")
        db.add(other_hod)
        db.commit()
        other_hod_id = other_hod.id
    res = client.patch(f"{API}/accounts/{other_hod_id}/status", json={"status": "suspended", "reason": "x"}, headers=headers)
    assert res.status_code in (403, 404)


def test_suspension_revokes_live_session(client, login, db_session):
    student_headers = login(STUDENT)
    student_id = _user_id(db_session, STUDENT)
    # Students belong to their HOD; the super admin cannot manage student accounts.
    res = client.patch(f"{API}/accounts/{student_id}/status",
                       json={"status": "suspended", "reason": "Disciplinary"}, headers=login(ADMIN_EMAIL))
    assert res.status_code == 403
    res = client.patch(f"{API}/accounts/{student_id}/status",
                       json={"status": "suspended", "reason": "Disciplinary"}, headers=login(HOD))
    assert res.status_code == 200
    assert client.get(f"{API}/auth/me", headers=student_headers).status_code == 401
    res = client.post(f"{API}/auth/login", json={"email": STUDENT, "password": DEMO_PASSWORD})
    assert res.status_code == 403


def test_rejection_requires_reason(client, login, db_session):
    pending_id = _user_id(db_session, "pending.cse@smartclass.edu")
    res = client.patch(f"{API}/accounts/{pending_id}/status", json={"status": "rejected"}, headers=login(HOD))
    assert res.status_code == 400


def test_audit_log_written_on_approval(client, login, db_session):
    from backend.app.models import AuditLog

    pending_id = _user_id(db_session, "pending.cse@smartclass.edu")
    client.patch(f"{API}/accounts/{pending_id}/status", json={"status": "active"}, headers=login(HOD))
    with db_session() as db:
        entry = db.scalar(select(AuditLog).where(AuditLog.action == "student.approved"))
        assert entry is not None
        assert entry.old_value == {"status": "pending"}
        assert entry.ip_address is not None
