"""HOD, teacher and student management: CRUD, status, password reset, isolation, audit."""

import json

from sqlalchemy import select

from backend.app.models import AuditLog, StudentCourseEnrollment, User
from backend.app.scripts.seed_demo import DEMO_PASSWORD
from tests.conftest import HOD_EMAIL, STUDENT_EMAIL, TEACHER_EMAIL

API = "/api/v1"


def _hod_payload(dept_id, **extra):
    return {"full_name": "Dr. Imran Shah", "email": "Imran.Shah@Test.edu", "password": "HodPass@123",
            "employee_id": " emp-hod-ee ", "department_id": dept_id, **extra}


# ── HODs ──────────────────────────────────────────────────────────────────


def test_only_super_admin_manages_hods(client, login, ee):
    for email in (HOD_EMAIL, TEACHER_EMAIL, STUDENT_EMAIL):
        headers = login(email)
        assert client.get(f"{API}/hods", headers=headers).status_code == 403
        assert client.post(f"{API}/hods", json=_hod_payload(ee["dept"]), headers=headers).status_code == 403


def test_create_hod_and_login(client, admin_h, ee, login, audit):
    res = client.post(f"{API}/hods", json=_hod_payload(ee["dept"]), headers=admin_h)
    assert res.status_code == 201, res.text
    hod = res.json()
    assert hod["email"] == "imran.shah@test.edu" and hod["employee_id"] == "EMP-HOD-EE"
    assert hod["is_current"] is True and hod["department_code"] == "EE" and hod["status"] == "active"
    headers = login("imran.shah@test.edu", "HodPass@123")
    dash = client.get(f"{API}/dashboard/hod", headers=headers).json()
    assert dash["department_name"] == "Electrical Engineering"
    entry = audit("hod.created")[0]
    assert "password" not in json.dumps(entry.new_value).lower()


def test_one_current_hod_per_department_and_replacement(client, admin_h, ids, login, audit):
    old_headers = login(HOD_EMAIL)
    payload = _hod_payload(ids["cse"], email="new.hod@test.edu", employee_id="EMP-HOD-NEW")
    conflict = client.post(f"{API}/hods", json=payload, headers=admin_h)
    assert conflict.status_code == 409 and "already has a HOD" in conflict.json()["detail"]

    res = client.post(f"{API}/hods", json={**payload, "replace_existing": True}, headers=admin_h)
    assert res.status_code == 201, res.text
    # The outgoing HOD lost the post, was suspended and their live session revoked.
    assert client.get(f"{API}/dashboard/hod", headers=old_headers).status_code == 401
    hods = client.get(f"{API}/hods", params={"department_id": ids["cse"]}, headers=admin_h).json()["items"]
    by_email = {h["email"]: h for h in hods}
    assert by_email[HOD_EMAIL]["is_current"] is False and by_email[HOD_EMAIL]["status"] == "suspended"
    assert by_email["new.hod@test.edu"]["is_current"] is True
    assert audit("hod.replaced")
    # A former HOD cannot simply be reactivated while they hold no department.
    old_user_id = by_email[HOD_EMAIL]["user_id"]
    res = client.patch(f"{API}/accounts/{old_user_id}/status", json={"status": "active"}, headers=admin_h)
    assert res.status_code == 409


def test_hod_unique_email_and_employee_id(client, admin_h, ee):
    dup_email = client.post(f"{API}/hods", json=_hod_payload(ee["dept"], email=HOD_EMAIL), headers=admin_h)
    assert dup_email.status_code == 409
    # Employee IDs are unique across all staff, including teachers.
    dup_emp = client.post(f"{API}/hods", json=_hod_payload(ee["dept"], employee_id="emp-t-101"), headers=admin_h)
    assert dup_emp.status_code == 409


def test_edit_and_move_hod(client, admin_h, ee, audit):
    hod = client.post(f"{API}/hods", json=_hod_payload(ee["dept"]), headers=admin_h).json()
    res = client.patch(f"{API}/hods/{hod['id']}", json={"full_name": "Prof. Imran Shah", "phone": "+92 300 1234567"},
                       headers=admin_h)
    assert res.status_code == 200 and res.json()["full_name"] == "Prof. Imran Shah"
    entry = audit("hod.updated")[0]
    assert entry.old_value["full_name"] == "Dr. Imran Shah" and entry.new_value["phone"] == "+92 300 1234567"


def test_suspend_reactivate_and_reset_hod_password(client, admin_h, ids, login, audit, db_session):
    with db_session() as db:
        hod_user_id = db.scalar(select(User.id).where(User.email == HOD_EMAIL))
    old = login(HOD_EMAIL)
    res = client.patch(f"{API}/accounts/{hod_user_id}/status", json={"status": "suspended", "reason": "Leave"},
                       headers=admin_h)
    assert res.status_code == 200 and audit("hod.suspended")
    assert client.get(f"{API}/dashboard/hod", headers=old).status_code == 401
    assert client.patch(f"{API}/accounts/{hod_user_id}/status", json={"status": "active"},
                        headers=admin_h).status_code == 200
    assert audit("hod.reactivated")
    res = client.post(f"{API}/accounts/{hod_user_id}/reset-password", json={"new_password": "Reset@2026x"},
                      headers=admin_h)
    assert res.status_code == 200
    login(HOD_EMAIL, "Reset@2026x")
    assert audit("hod.password_reset")


# ── Teachers ──────────────────────────────────────────────────────────────


def _teacher_payload(**extra):
    return {"full_name": "Qaiser Ijaz", "email": "qaiser@test.edu", "password": "Teach@1234",
            "employee_id": "EMP-T-202", "designation": "Assistant Professor", **extra}


def test_hod_creates_teacher_in_own_department(client, hod_h, ids, login, audit):
    res = client.post(f"{API}/teachers", json=_teacher_payload(), headers=hod_h)
    assert res.status_code == 201, res.text
    teacher = res.json()
    assert teacher["department_id"] == ids["cse"] and teacher["status"] == "active"
    login("qaiser@test.edu", "Teach@1234")
    entry = audit("teacher.created")[0]
    assert entry.department_id == ids["cse"] and "Teach@1234" not in json.dumps(entry.new_value)


def test_department_id_is_not_trusted_from_hod(client, hod_h, ee):
    res = client.post(f"{API}/teachers", json=_teacher_payload(department_id=ee["dept"]), headers=hod_h)
    assert res.status_code == 404


def test_admin_must_choose_department(client, admin_h, ee):
    assert client.post(f"{API}/teachers", json=_teacher_payload(), headers=admin_h).status_code == 422
    res = client.post(f"{API}/teachers", json=_teacher_payload(department_id=ee["dept"]), headers=admin_h)
    assert res.status_code == 201 and res.json()["department_code"] == "EE"


def test_teacher_list_search_filters_and_isolation(client, hod_h, admin_h, ids, ee):
    hod_list = client.get(f"{API}/teachers", headers=hod_h).json()
    assert {t["department_id"] for t in hod_list["items"]} == {ids["cse"]}
    assert client.get(f"{API}/teachers/{ee['teacher']}", headers=hod_h).status_code == 404
    found = client.get(f"{API}/teachers", params={"q": "emp-t-101"}, headers=hod_h).json()
    assert found["total"] == 1 and found["items"][0]["assignment_count"] == 2
    assert client.get(f"{API}/teachers", params={"status": "suspended"}, headers=hod_h).json()["total"] == 0
    assert client.get(f"{API}/teachers", headers=admin_h).json()["total"] == 2


def test_hod_edits_teacher_but_not_other_department(client, hod_h, ids, ee, audit):
    res = client.patch(f"{API}/teachers/{ids['teacher']}", json={"designation": "Senior Lecturer"}, headers=hod_h)
    assert res.status_code == 200 and res.json()["designation"] == "Senior Lecturer"
    assert audit("teacher.updated")[0].new_value == {"designation": "Senior Lecturer"}
    assert client.patch(f"{API}/teachers/{ee['teacher']}", json={"designation": "x"},
                        headers=hod_h).status_code == 404
    # HODs can never move a teacher out of their department.
    assert client.patch(f"{API}/teachers/{ids['teacher']}", json={"department_id": ee["dept"]},
                        headers=hod_h).status_code == 404


def test_teacher_with_assignments_cannot_change_department(client, admin_h, ids, ee):
    res = client.patch(f"{API}/teachers/{ids['teacher']}", json={"department_id": ee["dept"]}, headers=admin_h)
    assert res.status_code == 409


def test_hod_suspends_reactivates_and_resets_teacher(client, hod_h, ids, ee, login, audit):
    teacher_session = login(TEACHER_EMAIL)
    res = client.patch(f"{API}/accounts/{ids['teacher_user']}/status",
                       json={"status": "suspended", "reason": "Contract ended"}, headers=hod_h)
    assert res.status_code == 200 and audit("teacher.suspended")
    assert client.get(f"{API}/auth/me", headers=teacher_session).status_code == 401
    assert client.patch(f"{API}/accounts/{ids['teacher_user']}/status", json={"status": "active"},
                        headers=hod_h).status_code == 200
    res = client.post(f"{API}/accounts/{ids['teacher_user']}/reset-password",
                      json={"new_password": "NewTeach@99"}, headers=hod_h)
    assert res.status_code == 200
    login(TEACHER_EMAIL, "NewTeach@99")
    # Other department's teacher: invisible.
    assert client.patch(f"{API}/accounts/{ee['teacher_user']}/status",
                        json={"status": "suspended", "reason": "x"}, headers=hod_h).status_code == 404
    assert client.post(f"{API}/accounts/{ee['teacher_user']}/reset-password",
                       json={"new_password": "NewTeach@99"}, headers=hod_h).status_code == 404


def test_password_reset_rules(client, hod_h, admin_h, ids, db_session):
    weak = client.post(f"{API}/accounts/{ids['teacher_user']}/reset-password", json={"new_password": "short"},
                       headers=hod_h)
    assert weak.status_code == 422
    with db_session() as db:
        admin_id = db.scalar(select(User.id).where(User.role == "super_admin"))
    assert client.post(f"{API}/accounts/{admin_id}/reset-password", json={"new_password": "Valid@12345"},
                       headers=hod_h).status_code == 403
    # Nobody resets their own password through the admin endpoint.
    assert client.post(f"{API}/accounts/{admin_id}/reset-password", json={"new_password": "Valid@12345"},
                       headers=admin_h).status_code == 404


def test_duplicate_teacher_email_and_employee_id(client, hod_h):
    assert client.post(f"{API}/teachers", json=_teacher_payload(email=TEACHER_EMAIL),
                       headers=hod_h).status_code == 409
    assert client.post(f"{API}/teachers", json=_teacher_payload(employee_id="EMP-HOD-001"),
                       headers=hod_h).status_code == 409


# ── Students ──────────────────────────────────────────────────────────────


def _student_payload(ids, **extra):
    return {"full_name": "Hassan Raza", "email": "hassan@test.edu", "password": "Student@123",
            "registration_no": " f23cse04 ", "batch_id": ids["batch"], "semester_id": ids["semester"],
            "section_id": ids["section_b"], **extra}


def test_hod_creates_student(client, hod_h, ids, login, audit):
    res = client.post(f"{API}/students", json=_student_payload(ids), headers=hod_h)
    assert res.status_code == 201, res.text
    student = res.json()
    assert student["registration_no"] == "F23CSE04" and student["status"] == "active"
    assert student["section_name"] == "B" and student["semester_number"] == 6
    login("hassan@test.edu", "Student@123")
    assert audit("student.created")


def test_student_uniqueness(client, hod_h, ids):
    assert client.post(f"{API}/students", json=_student_payload(ids, registration_no="F23CSE01"),
                       headers=hod_h).status_code == 409
    assert client.post(f"{API}/students", json=_student_payload(ids, email=STUDENT_EMAIL.upper()),
                       headers=hod_h).status_code == 409


def test_student_placement_must_be_one_chain(client, hod_h, ids, ee):
    res = client.post(f"{API}/students", json=_student_payload(ids, section_id=ee["section"]), headers=hod_h)
    assert res.status_code == 422


def test_student_search_and_filters(client, hod_h, ids, ee):
    by_reg = client.get(f"{API}/students", params={"q": "f23cse01"}, headers=hod_h).json()
    assert [s["registration_no"] for s in by_reg["items"]] == ["F23CSE01"]
    by_name = client.get(f"{API}/students", params={"q": "sara"}, headers=hod_h).json()
    assert [s["registration_no"] for s in by_name["items"]] == ["F23CSE03"]
    by_email = client.get(f"{API}/students", params={"q": "student.cse@"}, headers=hod_h).json()
    assert by_email["total"] == 1
    pending = client.get(f"{API}/students", params={"status": "pending"}, headers=hod_h).json()
    assert [s["registration_no"] for s in pending["items"]] == ["F23CSE03"]
    assert client.get(f"{API}/students", params={"section_id": ids["section_b"]}, headers=hod_h).json()["total"] == 0
    # The EE student never appears for the CSE HOD, even when searched for directly.
    assert client.get(f"{API}/students", params={"q": "F24EE01"}, headers=hod_h).json()["total"] == 0
    assert client.get(f"{API}/students/{ee['student']}", headers=hod_h).status_code == 404


def test_edit_student_placement_moves_enrollments(client, hod_h, ids, audit, db_session):
    partial = client.patch(f"{API}/students/{ids['student']}", json={"section_id": ids["section_b"]}, headers=hod_h)
    assert partial.status_code == 422
    res = client.patch(f"{API}/students/{ids['student']}",
                       json={"batch_id": ids["batch"], "semester_id": ids["semester"], "section_id": ids["section_b"]},
                       headers=hod_h)
    assert res.status_code == 200 and res.json()["section_name"] == "B"
    with db_session() as db:
        sections = db.scalars(select(StudentCourseEnrollment.section_id).filter_by(
            student_id=ids["student"], is_active=True)).all()
    assert len(sections) == 4 and set(sections) == {ids["section_b"]}
    assert audit("student.updated")[0].new_value == {"section_id": ids["section_b"]}


def test_student_approval_rejection_and_suspension(client, hod_h, ids, login, audit):
    no_reason = client.patch(f"{API}/accounts/{ids['pending_user']}/status", json={"status": "rejected"},
                             headers=hod_h)
    assert no_reason.status_code == 400
    res = client.patch(f"{API}/accounts/{ids['pending_user']}/status",
                       json={"status": "rejected", "reason": "Wrong section"}, headers=hod_h)
    assert res.status_code == 200
    entry = audit("student.rejected")[0]
    assert entry.new_value == {"status": "rejected", "reason": "Wrong section"}
    # An approved student cannot be "rejected" — they are suspended instead.
    assert client.patch(f"{API}/accounts/{ids['student_user']}/status",
                        json={"status": "rejected", "reason": "x"}, headers=hod_h).status_code == 400
    assert client.patch(f"{API}/accounts/{ids['student_user']}/status",
                        json={"status": "suspended", "reason": "Fees"}, headers=hod_h).status_code == 200
    assert client.patch(f"{API}/accounts/{ids['student_user']}/status", json={"status": "active"},
                        headers=hod_h).status_code == 200
    assert audit("student.suspended") and audit("student.reactivated")
    login(STUDENT_EMAIL)


def test_no_plaintext_passwords_in_audit_log(client, admin_h, hod_h, ids, ee, db_session):
    client.post(f"{API}/teachers", json=_teacher_payload(), headers=hod_h)
    client.post(f"{API}/students", json=_student_payload(ids), headers=hod_h)
    client.post(f"{API}/hods", json=_hod_payload(ee["dept"]), headers=admin_h)
    client.post(f"{API}/accounts/{ids['teacher_user']}/reset-password", json={"new_password": "Secret@4321"},
                headers=hod_h)
    with db_session() as db:
        dump = json.dumps([[a.old_value, a.new_value] for a in db.scalars(select(AuditLog))])
    for secret in ("Teach@1234", "Student@123", "HodPass@123", "Secret@4321", DEMO_PASSWORD, "$2b$"):
        assert secret not in dump
