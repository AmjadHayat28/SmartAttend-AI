"""Teacher assignments (HOD) and student enrollments (the class's own teacher)."""

from datetime import date

import pytest
from sqlalchemy import func, select

from backend.app.models import AuditLog, StudentCourseEnrollment, TeacherCourseAssignment
from tests.conftest import ADMIN_EMAIL, HOD_EMAIL, STUDENT_EMAIL, TEACHER_EMAIL

API = "/api/v1"


# ── Teacher assignments ───────────────────────────────────────────────────


def test_assignment_appears_on_teacher_dashboard(client, hod_h, ids, login, audit):
    teacher_h = login(TEACHER_EMAIL)
    before = {c["course_code"] for c in client.get(f"{API}/dashboard/teacher/classes", headers=teacher_h).json()}
    assert before == {"CS-321", "CS-321L"}

    res = client.post(f"{API}/assignments", json={"teacher_id": ids["teacher"], "course_id": ids["courses"]["MA-301"],
                                                  "section_id": ids["section_b"]}, headers=hod_h)
    assert res.status_code == 201, res.text
    assignment = res.json()
    assert assignment["batch_name"] == "F23" and assignment["semester_number"] == 6
    assert assignment["section_name"] == "B"
    classes = client.get(f"{API}/dashboard/teacher/classes", headers=teacher_h).json()
    assert ("MA-301", "B") in {(c["course_code"], c["section"]) for c in classes}

    assert client.delete(f"{API}/assignments/{assignment['id']}", headers=hod_h).status_code == 204
    classes = client.get(f"{API}/dashboard/teacher/classes", headers=teacher_h).json()
    assert "MA-301" not in {c["course_code"] for c in classes}
    assert audit("teacher_assignment.created") and audit("teacher_assignment.removed")
    # Removing twice is a 404; re-creating reactivates the same row.
    assert client.delete(f"{API}/assignments/{assignment['id']}", headers=hod_h).status_code == 404
    again = client.post(f"{API}/assignments", json={"teacher_id": ids["teacher"], "course_id": ids["courses"]["MA-301"],
                                                    "section_id": ids["section_b"]}, headers=hod_h)
    assert again.status_code == 201 and again.json()["id"] == assignment["id"]


def test_duplicate_assignment_rejected(client, hod_h, ids):
    res = client.post(f"{API}/assignments", json={"teacher_id": ids["teacher"], "course_id": ids["courses"]["CS-321"],
                                                  "section_id": ids["section_a"]}, headers=hod_h)
    assert res.status_code == 409


def test_each_hod_assigns_and_removes_in_own_department(client, ee_hod_h, hod_h, ee, login, audit):
    ee_teacher_h = login("teacher.ee@test.edu")
    assert client.get(f"{API}/enrollments/classes", headers=ee_teacher_h).json() == []
    res = client.post(f"{API}/assignments", json={"teacher_id": ee["teacher"], "course_id": ee["course"],
                                                  "section_id": ee["section"]}, headers=ee_hod_h)
    assert res.status_code == 201, res.text
    created = res.json()
    assert created["department_code"] == "EE"
    assert [a["id"] for a in client.get(f"{API}/assignments", headers=ee_hod_h).json()["items"]] == [created["id"]]
    classes = client.get(f"{API}/enrollments/classes", headers=ee_teacher_h).json()
    assert [c["course_code"] for c in classes] == ["EE-101"]  # the teacher sees the class at once
    # The CSE HOD can neither see nor remove it.
    assert created["id"] not in {a["id"] for a in client.get(f"{API}/assignments", headers=hod_h).json()["items"]}
    assert client.delete(f"{API}/assignments/{created['id']}", headers=hod_h).status_code == 404

    assert client.delete(f"{API}/assignments/{created['id']}", headers=ee_hod_h).status_code == 204
    assert client.get(f"{API}/enrollments/classes", headers=ee_teacher_h).json() == []
    assert len(audit("teacher_assignment.created")) == 1 and len(audit("teacher_assignment.removed")) == 1


def test_hod_cannot_assign_across_departments(client, hod_h, ids, ee):
    for payload in (
        {"teacher_id": ee["teacher"], "course_id": ids["courses"]["CS-321"], "section_id": ids["section_a"]},
        {"teacher_id": ids["teacher"], "course_id": ee["course"], "section_id": ids["section_a"]},
        {"teacher_id": ids["teacher"], "course_id": ids["courses"]["CS-321"], "section_id": ee["section"]},
    ):
        assert client.post(f"{API}/assignments", json=payload, headers=hod_h).status_code == 404


def test_hod_cannot_see_or_remove_other_department_assignment(client, ee_hod_h, hod_h, ee):
    created = client.post(f"{API}/assignments", json={"teacher_id": ee["teacher"], "course_id": ee["course"],
                                                      "section_id": ee["section"]}, headers=ee_hod_h).json()
    assert client.delete(f"{API}/assignments/{created['id']}", headers=hod_h).status_code == 404
    listed = client.get(f"{API}/assignments", headers=hod_h).json()
    assert created["id"] not in {a["id"] for a in listed["items"]}


def test_suspended_teacher_and_inactive_course_cannot_be_assigned(client, hod_h, ids):
    client.patch(f"{API}/courses/{ids['courses']['MA-301']}", json={"is_active": False}, headers=hod_h)
    res = client.post(f"{API}/assignments", json={"teacher_id": ids["teacher"], "course_id": ids["courses"]["MA-301"],
                                                  "section_id": ids["section_a"]}, headers=hod_h)
    assert res.status_code == 422
    client.patch(f"{API}/accounts/{ids['teacher_user']}/status", json={"status": "suspended", "reason": "x"},
                 headers=hod_h)
    res = client.post(f"{API}/assignments", json={"teacher_id": ids["teacher"], "course_id": ids["courses"]["CS-341"],
                                                  "section_id": ids["section_a"]}, headers=hod_h)
    assert res.status_code == 422


@pytest.mark.parametrize("email", [ADMIN_EMAIL, TEACHER_EMAIL, STUDENT_EMAIL])
def test_only_hods_manage_assignments(client, login, ids, db_session, email):
    """Super admin, teachers and students: 403 on every assignment-management endpoint."""
    headers = login(email)
    with db_session() as db:
        existing = db.scalar(select(TeacherCourseAssignment.id).where(TeacherCourseAssignment.teacher_id == ids["teacher"]))
    body = {"teacher_id": ids["teacher"], "course_id": ids["courses"]["MA-301"], "section_id": ids["section_b"]}
    assert client.get(f"{API}/assignments", headers=headers).status_code == 403
    assert client.post(f"{API}/assignments", json=body, headers=headers).status_code == 403
    assert client.delete(f"{API}/assignments/{existing}", headers=headers).status_code == 403
    with db_session() as db:
        assert db.scalar(select(func.count(TeacherCourseAssignment.id))
                         .where(TeacherCourseAssignment.is_active.is_(True))) == 2  # the seeded pair, untouched


def test_existing_assignments_keep_working_for_the_teacher(client, login, db_session, ids):
    """Stored assignments are unaffected by who manages them: classes, enrollments and attendance."""
    teacher_h = login(TEACHER_EMAIL)
    classes = client.get(f"{API}/enrollments/classes", headers=teacher_h).json()
    assert {c["course_code"] for c in classes} == {"CS-321", "CS-321L"}
    assert {c["course_code"] for c in client.get(f"{API}/attendance/classes", headers=teacher_h).json()} == {"CS-321", "CS-321L"}
    cs321 = next(c["id"] for c in classes if c["course_code"] == "CS-321")
    assert client.get(f"{API}/enrollments", params={"assignment_id": cs321}, headers=teacher_h).json()["total"] == 1
    started = client.post(f"{API}/attendance/sessions", headers=teacher_h,
                          json={"assignment_id": cs321, "session_date": date.today().isoformat(), "session_number": 1})
    assert started.status_code == 201


# ── Student enrollments: the class's own teacher ──────────────────────────


@pytest.fixture()
def teacher_h(login):
    return login(TEACHER_EMAIL)


@pytest.fixture()
def cs321(db_session, ids):
    """The CSE teacher's CS-321 / Section A assignment id."""
    with db_session() as db:
        return db.scalar(select(TeacherCourseAssignment.id).where(
            TeacherCourseAssignment.course_id == ids["courses"]["CS-321"],
            TeacherCourseAssignment.section_id == ids["section_a"]))


def _new_student(client, hod_h, ids, reg, section="section_a"):
    return client.post(f"{API}/students", headers=hod_h, json={
        "full_name": f"Student {reg}", "email": f"{reg.lower()}@test.edu", "password": "Student@123",
        "registration_no": reg, "batch_id": ids["batch"], "semester_id": ids["semester"],
        "section_id": ids[section]}).json()


def _count(db_session, **filters) -> int:
    with db_session() as db:
        return db.scalar(select(func.count(StudentCourseEnrollment.id)).filter_by(is_active=True, **filters))


def test_teacher_sees_own_classes_and_their_students(client, teacher_h, cs321):
    classes = client.get(f"{API}/enrollments/classes", headers=teacher_h).json()
    assert {(c["course_code"], c["section_name"]) for c in classes} == {("CS-321", "A"), ("CS-321L", "A")}
    enrolled = client.get(f"{API}/enrollments", params={"assignment_id": cs321}, headers=teacher_h).json()
    assert [e["registration_no"] for e in enrolled["items"]] == ["F23CSE01"]
    candidates = client.get(f"{API}/enrollments/candidates", params={"assignment_id": cs321}, headers=teacher_h).json()
    assert [c["registration_no"] for c in candidates["items"]] == ["F23CSE03"]  # pending, not yet enrolled
    # Search by registration number or name.
    for q, total in (("cse01", 1), ("ali", 1), ("nobody", 0)):
        res = client.get(f"{API}/enrollments", params={"assignment_id": cs321, "q": q}, headers=teacher_h).json()
        assert res["total"] == total, q


def test_teacher_enrolls_and_removes_in_own_class(client, teacher_h, cs321, ids, audit):
    body = {"assignment_id": cs321, "student_id": ids["pending"]}
    res = client.post(f"{API}/enrollments", json=body, headers=teacher_h)
    assert res.status_code == 201, res.text
    enrollment = res.json()
    assert (enrollment["registration_no"], enrollment["course_code"], enrollment["section_name"]) == ("F23CSE03", "CS-321", "A")
    assert client.post(f"{API}/enrollments", json=body, headers=teacher_h).status_code == 409

    assert client.delete(f"{API}/enrollments/{enrollment['id']}", headers=teacher_h).status_code == 204
    assert client.delete(f"{API}/enrollments/{enrollment['id']}", headers=teacher_h).status_code == 404
    listed = client.get(f"{API}/enrollments", params={"assignment_id": cs321}, headers=teacher_h).json()
    assert "F23CSE03" not in {e["registration_no"] for e in listed["items"]}
    again = client.post(f"{API}/enrollments", json=body, headers=teacher_h)  # reactivates the same row
    assert again.status_code == 201 and again.json()["id"] == enrollment["id"]

    created, removed = audit("student_enrollment.created"), audit("student_enrollment.removed")
    assert len(created) == 2 and len(removed) == 1
    for entry in (created[0], removed[0]):
        assert entry.user_id == ids["teacher_user"] and entry.timestamp is not None
        assert entry.new_value["teacher_id"] == ids["teacher"] and entry.new_value["student_id"] == ids["pending"]
        assert entry.new_value["course_id"] == ids["courses"]["CS-321"]
        assert entry.new_value["section_id"] == ids["section_a"]


def test_student_must_be_in_the_class_section(client, teacher_h, hod_h, cs321, ids, ee):
    other_section = _new_student(client, hod_h, ids, "F23CSE50", section="section_b")
    for student_id in (other_section["id"], ee["student"], 999999):
        res = client.post(f"{API}/enrollments", json={"assignment_id": cs321, "student_id": student_id},
                          headers=teacher_h)
        assert res.status_code == 404, student_id
    client.patch(f"{API}/accounts/{ids['pending_user']}/status", json={"status": "rejected", "reason": "x"},
                 headers=hod_h)
    assert client.post(f"{API}/enrollments", json={"assignment_id": cs321, "student_id": ids["pending"]},
                       headers=teacher_h).status_code == 422


def test_teacher_cannot_touch_another_teachers_class(client, teacher_h, hod_h, ids, db_session, login):
    client.post(f"{API}/teachers", headers=hod_h, json={
        "full_name": "Co Teacher", "email": "co@test.edu", "password": "Teach@1234", "employee_id": "EMP-T-777"})
    co_id = client.get(f"{API}/teachers", params={"q": "EMP-T-777"}, headers=hod_h).json()["items"][0]["id"]
    ma301 = client.post(f"{API}/assignments", headers=hod_h, json={
        "teacher_id": co_id, "course_id": ids["courses"]["MA-301"], "section_id": ids["section_a"]}).json()["id"]
    with db_session() as db:
        ma301_enrollment = db.scalar(select(StudentCourseEnrollment.id).filter_by(
            student_id=ids["student"], course_id=ids["courses"]["MA-301"]))

    # Same department, same section — but not this teacher's class.
    assert client.get(f"{API}/enrollments", params={"assignment_id": ma301}, headers=teacher_h).status_code == 404
    assert client.get(f"{API}/enrollments/candidates", params={"assignment_id": ma301},
                      headers=teacher_h).status_code == 404
    assert client.post(f"{API}/enrollments", json={"assignment_id": ma301, "student_id": ids["pending"]},
                       headers=teacher_h).status_code == 404
    assert client.post(f"{API}/enrollments/bulk", json={"assignment_id": ma301}, headers=teacher_h).status_code == 404
    assert client.delete(f"{API}/enrollments/{ma301_enrollment}", headers=teacher_h).status_code == 404
    assert _count(db_session, course_id=ids["courses"]["MA-301"]) == 1  # untouched

    # The assigned co-teacher can; once the assignment is removed, nobody can through it.
    co_h = login("co@test.edu", "Teach@1234")
    assert client.delete(f"{API}/enrollments/{ma301_enrollment}", headers=co_h).status_code == 204
    client.delete(f"{API}/assignments/{ma301}", headers=hod_h)
    assert client.post(f"{API}/enrollments/bulk", json={"assignment_id": ma301}, headers=co_h).status_code == 404


def test_teacher_cannot_cross_department(client, teacher_h, cs321, ids, ee, ee_hod_h, login):
    ee_assignment = client.post(f"{API}/assignments", headers=ee_hod_h, json={
        "teacher_id": ee["teacher"], "course_id": ee["course"], "section_id": ee["section"]}).json()["id"]
    ee_h = login("teacher.ee@test.edu")
    assert client.post(f"{API}/enrollments", json={"assignment_id": ee_assignment, "student_id": ee["student"]},
                       headers=teacher_h).status_code == 404
    assert client.get(f"{API}/enrollments", params={"assignment_id": ee_assignment},
                      headers=teacher_h).status_code == 404
    # …and the EE teacher can neither use a CSE class nor pull a CSE student into their own.
    assert client.post(f"{API}/enrollments", json={"assignment_id": cs321, "student_id": ids["pending"]},
                       headers=ee_h).status_code == 404
    assert client.post(f"{API}/enrollments", json={"assignment_id": ee_assignment, "student_id": ids["pending"]},
                       headers=ee_h).status_code == 404
    ok = client.post(f"{API}/enrollments", json={"assignment_id": ee_assignment, "student_id": ee["student"]},
                     headers=ee_h)
    assert ok.status_code == 201


def test_bulk_enroll_dry_run_then_commit_then_rerun(client, teacher_h, hod_h, cs321, ids, db_session, audit):
    for reg in ("F23CSE04", "F23CSE05"):
        _new_student(client, hod_h, ids, reg)
    _new_student(client, hod_h, ids, "F23CSE60", section="section_b")  # not in this class
    suspended = _new_student(client, hod_h, ids, "F23CSE06")
    client.patch(f"{API}/accounts/{suspended['user_id']}/status", json={"status": "suspended", "reason": "x"},
                 headers=hod_h)
    course = ids["courses"]["CS-321"]

    preview = client.post(f"{API}/enrollments/bulk", json={"assignment_id": cs321, "dry_run": True},
                          headers=teacher_h).json()
    assert preview["dry_run"] is True and preview["students_in_section"] == 5 and preview["students_eligible"] == 4
    assert (preview["newly_enrolled"], preview["already_enrolled"], preview["skipped"]) == (3, 1, 1)
    assert "F23CSE06 skipped" in " ".join(preview["errors"])
    assert _count(db_session, course_id=course) == 1  # nothing written

    result = client.post(f"{API}/enrollments/bulk", json={"assignment_id": cs321}, headers=teacher_h).json()
    assert (result["newly_enrolled"], result["already_enrolled"]) == (3, 1)
    assert _count(db_session, course_id=course) == 4
    rerun = client.post(f"{API}/enrollments/bulk", json={"assignment_id": cs321}, headers=teacher_h).json()
    assert (rerun["newly_enrolled"], rerun["already_enrolled"]) == (0, 4)
    assert _count(db_session, course_id=course) == 4  # no duplicates

    first, second = sorted(audit("student_enrollment.bulk"), key=lambda e: e.id)
    assert first.user_id == ids["teacher_user"] and first.new_value["teacher_id"] == ids["teacher"]
    assert first.new_value["newly_enrolled"] == 3 and len(first.new_value["student_ids"]) == 3
    assert first.new_value["course_id"] == course and first.new_value["section_id"] == ids["section_a"]
    assert second.new_value["newly_enrolled"] == 0


def test_inactive_course_blocks_enrollment_changes(client, teacher_h, hod_h, cs321, ids):
    client.patch(f"{API}/courses/{ids['courses']['CS-321']}", json={"is_active": False}, headers=hod_h)
    assert client.post(f"{API}/enrollments/bulk", json={"assignment_id": cs321}, headers=teacher_h).status_code == 422
    assert client.post(f"{API}/enrollments", json={"assignment_id": cs321, "student_id": ids["pending"]},
                       headers=teacher_h).status_code == 422


@pytest.mark.parametrize("who", ["hod", "admin", "student"])
def test_only_teachers_manage_enrollments(client, who, login, cs321, ids, db_session):
    """HODs assign classes but no longer enroll students; the super admin and students never could."""
    headers = login({"hod": HOD_EMAIL, "admin": ADMIN_EMAIL, "student": STUDENT_EMAIL}[who])
    with db_session() as db:
        enrollment_id = db.scalar(select(StudentCourseEnrollment.id).filter_by(student_id=ids["student"]))
        audits_before = db.scalar(select(func.count(AuditLog.id)))
    for method, path, kwargs in (
        ("get", "/enrollments/classes", {}),
        ("get", "/enrollments", {"params": {"assignment_id": cs321}}),
        ("get", "/enrollments/candidates", {"params": {"assignment_id": cs321}}),
        ("post", "/enrollments", {"json": {"assignment_id": cs321, "student_id": ids["pending"]}}),
        ("post", "/enrollments/bulk", {"json": {"assignment_id": cs321}}),
        ("delete", f"/enrollments/{enrollment_id}", {}),
    ):
        assert getattr(client, method)(f"{API}{path}", headers=headers, **kwargs).status_code == 403, path
    assert _count(db_session) == 4
    with db_session() as db:
        assert db.scalar(select(func.count(AuditLog.id))) == audits_before
    if who == "hod":  # the HOD keeps teacher-assignment management
        assert client.get(f"{API}/assignments", headers=headers).status_code == 200
