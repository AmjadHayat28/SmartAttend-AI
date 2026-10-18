"""Role architecture: the super admin is a SYSTEM administrator (departments → HODs → teachers),
not an attendance or student-management user. Enforced by the API, not just hidden in the UI."""

import pytest
from sqlalchemy import func, select

from backend.app.models import TeacherCourseAssignment, User
from tests.conftest import STUDENT_EMAIL
from tests.test_attendance import API, cls, finalize, mark, start, teacher_h  # noqa: F401


@pytest.fixture()
def final(client, teacher_h, cls):
    s = start(client, teacher_h, cls["assignment"]).json()["session"]
    s = mark(client, teacher_h, s, ["present"] * 5).json()
    return finalize(client, teacher_h, s).json()


def _user_id(db_session, email):
    with db_session() as db:
        return db.scalar(select(User.id).where(User.email == email))


# ── What the super admin can no longer reach ──────────────────────────────


def test_super_admin_has_no_attendance_access(client, admin_h, final):
    sid, rid = final["id"], final["records"][0]["id"]
    for method, path, body in (
        ("get", "/attendance/sessions", None),
        ("get", f"/attendance/sessions/{sid}", None),
        ("post", f"/attendance/sessions/{sid}/delete", {"reason": "Not my job at all"}),
        ("post", f"/attendance/records/{rid}/correct", {"status": "absent", "reason": "Not my job"}),
        ("get", f"/attendance/sessions/{sid}/recognition", None),
        ("get", "/attendance/images/1", None),
        ("get", "/attendance/classes", None),
    ):
        kwargs = {"json": body} if body is not None else {}
        res = getattr(client, method)(f"{API}{path}", headers=admin_h, **kwargs)
        assert res.status_code == 403, (path, res.status_code)


def test_super_admin_has_no_student_management(client, admin_h, ids, db_session):
    student_user = _user_id(db_session, STUDENT_EMAIL)
    for method, path, body in (
        ("get", "/students", None),
        ("get", f"/students/{ids['student']}", None),
        ("post", "/students", {"full_name": "X", "email": "x@test.edu", "password": "Student@123",
                               "registration_no": "F23CSE77", "batch_id": ids["batch"],
                               "semester_id": ids["semester"], "section_id": ids["section_a"]}),
        ("patch", f"/students/{ids['student']}", {"full_name": "Renamed"}),
        ("get", "/accounts/pending-students", None),
        ("get", "/face-enrollments", None),
        ("get", f"/face-enrollments/{ids['student']}", None),
        ("get", "/enrollments", None),
        ("get", "/batches", None),
        ("get", "/semesters", None),
        ("get", "/sections", None),
    ):
        kwargs = {"json": body} if body is not None else {}
        res = getattr(client, method)(f"{API}{path}", headers=admin_h, **kwargs)
        assert res.status_code == 403, (path, res.status_code)
    # Student accounts (status / password) belong to the department's HOD.
    assert client.patch(f"{API}/accounts/{student_user}/status", headers=admin_h,
                        json={"status": "suspended", "reason": "x"}).status_code == 403
    assert client.post(f"{API}/accounts/{student_user}/reset-password", headers=admin_h,
                       json={"new_password": "NewPass@123"}).status_code == 403
    assert client.get(f"{API}/students/{ids['student']}/profile-photo", headers=admin_h).status_code == 404


def test_admin_dashboard_is_a_system_dashboard(client, admin_h, final):
    data = client.get(f"{API}/dashboard/admin", headers=admin_h).json()
    for key in ("today_attendance_pct", "students", "pending_approvals"):
        assert key not in data
    assert data["departments"] == 2 and data["active_departments"] == 2
    assert data["hods"] == 1 and data["active_hods"] == 1 and data["departments_without_hod"] == 1  # EE
    assert data["teachers"] >= 1 and data["active_teachers"] >= 1 and data["suspended_staff"] == 0
    assert all(not a["action"].startswith(("attendance.", "student")) for a in data["recent_activity"])


# ── What the super admin still manages ────────────────────────────────────


def test_super_admin_manages_departments_hods_and_teachers(client, admin_h, ids, ee, login, db_session, audit):
    dept = client.post(f"{API}/departments", headers=admin_h, json={"name": "Physics", "code": "PHY"})
    assert dept.status_code == 201
    assert client.patch(f"{API}/departments/{dept.json()['id']}", headers=admin_h,
                        json={"description": "Natural sciences"}).status_code == 200

    hod = client.post(f"{API}/hods", headers=admin_h, json={
        "full_name": "Physics Head", "email": "hod.phy@test.edu", "password": "HodPass@123",
        "employee_id": "EMP-HOD-PHY", "department_id": dept.json()["id"]})
    assert hod.status_code == 201
    teacher = client.post(f"{API}/teachers", headers=admin_h, json={
        "full_name": "New Teacher", "email": "nt@test.edu", "password": "Teach@1234",
        "employee_id": "EMP-T-555", "department_id": ee["dept"]})
    assert teacher.status_code == 201
    assert client.patch(f"{API}/teachers/{teacher.json()['id']}", headers=admin_h,
                        json={"full_name": "Renamed Teacher"}).status_code == 200
    assert client.get(f"{API}/teachers", headers=admin_h).json()["total"] >= 3

    # Staff account status and password resets.
    for email in ("hod.phy@test.edu", "nt@test.edu"):
        uid = _user_id(db_session, email)
        assert client.patch(f"{API}/accounts/{uid}/status", headers=admin_h,
                            json={"status": "suspended", "reason": "Leave of absence"}).status_code == 200
        assert client.patch(f"{API}/accounts/{uid}/status", headers=admin_h,
                            json={"status": "active"}).status_code == 200
        assert client.post(f"{API}/accounts/{uid}/reset-password", headers=admin_h,
                           json={"new_password": "Fresh@12345"}).status_code == 200
    login("nt@test.edu", "Fresh@12345")
    suspended = client.patch(f"{API}/accounts/{_user_id(db_session, 'nt@test.edu')}/status", headers=admin_h,
                             json={"status": "suspended", "reason": "Contract ended"})
    assert suspended.status_code == 200
    data = client.get(f"{API}/dashboard/admin", headers=admin_h).json()
    assert data["suspended_staff"] == 1 and data["departments_without_hod"] == 1  # EE still has none
    assert {a["action"] for a in data["recent_activity"]} & {"teacher.suspended", "hod.created", "department.created"}


def test_super_admin_has_no_teacher_assignment_management(client, admin_h, hod_h, ee, ids, db_session):
    """Teacher-to-class assignments belong to the department's HOD; the super admin gets 403."""
    with db_session() as db:
        existing = db.scalar(select(TeacherCourseAssignment.id).where(
            TeacherCourseAssignment.teacher_id == ids["teacher"]))
        before = db.scalar(select(func.count(TeacherCourseAssignment.id)).where(
            TeacherCourseAssignment.is_active.is_(True)))
    for method, path, body in (
        ("get", "/assignments", None),
        ("post", "/assignments", {"teacher_id": ee["teacher"], "course_id": ee["course"], "section_id": ee["section"]}),
        ("delete", f"/assignments/{existing}", None),
    ):
        kwargs = {"json": body} if body is not None else {}
        assert getattr(client, method)(f"{API}{path}", headers=admin_h, **kwargs).status_code == 403, (method, path)
    with db_session() as db:
        assert db.scalar(select(func.count(TeacherCourseAssignment.id)).where(
            TeacherCourseAssignment.is_active.is_(True))) == before  # nothing created or removed
    # Activity feed: departments and staff only, never the HOD's assignments.
    assert client.post(f"{API}/assignments", headers=hod_h, json={
        "teacher_id": ids["teacher"], "course_id": ids["courses"]["MA-301"], "section_id": ids["section_b"]}).status_code == 201
    actions = {a["action"] for a in client.get(f"{API}/dashboard/admin", headers=admin_h).json()["recent_activity"]}
    assert not any(a.startswith("teacher_assignment.") for a in actions)


# ── HOD: the department authority, isolated ───────────────────────────────


def test_hod_manages_department_students_only_in_own_department(client, hod_h, ee_hod_h, ids, ee):
    assert client.get(f"{API}/students/{ids['student']}", headers=hod_h).status_code == 200
    assert client.patch(f"{API}/students/{ids['student']}", headers=hod_h,
                        json={"full_name": "Renamed Student"}).status_code == 200
    assert client.get(f"{API}/accounts/pending-students", headers=hod_h).status_code == 200
    for path in ("/teachers", "/batches", "/semesters", "/sections", "/courses", "/assignments",
                 "/face-enrollments"):
        assert client.get(f"{API}{path}", headers=hod_h).status_code == 200, path
    # Course enrollments belong to the class's teacher, not the HOD.
    assert client.get(f"{API}/enrollments/classes", headers=hod_h).status_code == 403
    # Another department's HOD sees none of it.
    assert client.get(f"{API}/students/{ids['student']}", headers=ee_hod_h).status_code == 404
    assert client.patch(f"{API}/students/{ids['student']}", headers=ee_hod_h,
                        json={"full_name": "Hacked"}).status_code == 404
    assert client.get(f"{API}/students/{ee['student']}", headers=hod_h).status_code == 404


# ── Attendance sessions: the teacher's alone ──────────────────────────────


def test_hod_has_no_attendance_session_access(client, hod_h, teacher_h, final, login):
    """Even for their own department's session, the HOD is refused every attendance endpoint."""
    sid, rid = final["id"], final["records"][0]["id"]
    for method, path, body in (
        ("get", "/attendance/sessions", None),
        ("get", f"/attendance/sessions/{sid}", None),
        ("get", "/attendance/images/1", None),
        ("get", f"/attendance/sessions/{sid}/recognition", None),
        ("post", f"/attendance/records/{rid}/correct", {"status": "absent", "reason": "HOD override attempt"}),
        ("post", f"/attendance/sessions/{sid}/delete", {"reason": "HOD delete attempt"}),
        ("get", "/attendance/classes", None),
        ("post", "/attendance/sessions", {"assignment_id": 1, "session_date": final["session_date"]}),
    ):
        kwargs = {"json": body} if body is not None else {}
        res = getattr(client, method)(f"{API}{path}", headers=hod_h, **kwargs)
        assert res.status_code == 403, (path, res.status_code)
    # The teacher still has it all, and the student's own attendance view still works.
    assert client.get(f"{API}/attendance/sessions/{sid}", headers=teacher_h).json()["can_correct"] is True
    subjects = client.get(f"{API}/dashboard/student/subjects", headers=login(STUDENT_EMAIL))
    assert subjects.status_code == 200
    card = next(c for c in subjects.json()["subjects"] if c["course_code"] == "CS-321")
    assert card["present"] == 1 and card["percentage"] == 100.0
