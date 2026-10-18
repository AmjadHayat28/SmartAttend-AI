"""Batches, semesters, sections and courses: CRUD, validation, duplicates, isolation, audit."""

import pytest

from tests.conftest import STUDENT_EMAIL, TEACHER_EMAIL

API = "/api/v1"


# ── Access control ────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/batches", "/semesters", "/sections", "/courses", "/academics/structure"])
def test_teachers_and_students_cannot_manage_academics(client, login, path):
    for email in (TEACHER_EMAIL, STUDENT_EMAIL):
        assert client.get(f"{API}{path}", headers=login(email)).status_code == 403
    assert client.get(f"{API}{path}").status_code == 401


def test_structure_is_department_scoped(client, admin_h, hod_h, ee):
    hod_tree = client.get(f"{API}/academics/structure", headers=hod_h).json()
    assert [d["code"] for d in hod_tree] == ["CSE"]
    admin_tree = client.get(f"{API}/academics/structure", headers=admin_h).json()
    assert {d["code"] for d in admin_tree} == {"CSE", "EE"}


# ── Batches ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/batches", "/semesters", "/sections"])
def test_super_admin_does_not_manage_academics(client, admin_h, path):
    """Department academics belong to the HOD; the super admin administers departments and staff."""
    assert client.get(f"{API}{path}", headers=admin_h).status_code == 403
    assert client.post(f"{API}{path}", json={}, headers=admin_h).status_code == 403
    assert client.post(f"{API}/courses", json={"code": "X-1", "title": "X"}, headers=admin_h).status_code == 403
    assert client.patch(f"{API}/courses/1", json={"title": "X"}, headers=admin_h).status_code == 403
    # Courses were readable only for the Teacher Assignments screen, which is now the HOD's alone.
    assert client.get(f"{API}/courses", headers=admin_h).status_code == 403
    assert client.get(f"{API}/courses/1", headers=admin_h).status_code == 403


def test_hod_batch_crud(client, ee_hod_h, audit):
    res = client.post(f"{API}/batches", json={"name": "  Fall   2024 ", "start_year": 2024, "end_year": 2028},
                      headers=ee_hod_h)
    assert res.status_code == 201, res.text
    batch = res.json()
    assert batch["name"] == "Fall 2024" and batch["department_code"] == "EE"

    res = client.patch(f"{API}/batches/{batch['id']}", json={"is_active": False}, headers=ee_hod_h)
    assert res.status_code == 200 and res.json()["is_active"] is False
    assert audit("batch.created")[0].new_value["name"] == "Fall 2024"
    updated = audit("batch.updated")[0]
    assert updated.old_value == {"is_active": True} and updated.new_value == {"is_active": False}


def test_batch_validation_and_duplicates(client, hod_h):
    bad = client.post(f"{API}/batches", json={"name": "X1", "start_year": 2025, "end_year": 2020}, headers=hod_h)
    assert bad.status_code == 422
    dup = client.post(f"{API}/batches", json={"name": "f23", "start_year": 2023}, headers=hod_h)
    assert dup.status_code == 409  # case-insensitive within the department


def test_hod_batches_forced_into_own_department(client, hod_h, ids, ee):
    res = client.post(f"{API}/batches", json={"name": "Spring 2025", "start_year": 2025}, headers=hod_h)
    assert res.status_code == 201 and res.json()["department_id"] == ids["cse"]
    # Naming another department is refused without revealing it.
    res = client.post(f"{API}/batches", json={"name": "Spring 2025", "start_year": 2025,
                                              "department_id": ee["dept"]}, headers=hod_h)
    assert res.status_code == 404
    assert client.patch(f"{API}/batches/{ee['batch']}", json={"name": "Hacked"}, headers=hod_h).status_code == 404
    assert client.get(f"{API}/batches/{ee['batch']}", headers=hod_h).status_code == 404
    listed = client.get(f"{API}/batches", headers=hod_h).json()
    assert {b["department_id"] for b in listed["items"]} == {ids["cse"]}
    assert client.get(f"{API}/batches", params={"department_id": ee["dept"]}, headers=hod_h).json()["total"] == 0


def test_same_batch_name_allowed_in_other_department(client, ee_hod_h):
    res = client.post(f"{API}/batches", json={"name": "F23", "start_year": 2023}, headers=ee_hod_h)
    assert res.status_code == 201


# ── Semesters ─────────────────────────────────────────────────────────────


def test_semester_crud_default_name_and_current_flag(client, hod_h, ids, audit):
    res = client.post(f"{API}/semesters", json={"batch_id": ids["batch"], "number": 7, "is_current": True},
                      headers=hod_h)
    assert res.status_code == 201, res.text
    sem7 = res.json()
    assert sem7["name"] == "Semester 7" and sem7["department_id"] == ids["cse"]
    # Only one current semester per batch: semester 6 was current and no longer is.
    sem6 = client.get(f"{API}/semesters/{ids['semester']}", headers=hod_h).json()
    assert sem6["is_current"] is False

    res = client.patch(f"{API}/semesters/{sem7['id']}", json={"name": "Fall 2026"}, headers=hod_h)
    assert res.json()["name"] == "Fall 2026"
    assert audit("semester.created") and audit("semester.updated")[0].new_value == {"name": "Fall 2026"}


def test_semester_duplicates_and_validation(client, hod_h, ids):
    dup = client.post(f"{API}/semesters", json={"batch_id": ids["batch"], "number": 6}, headers=hod_h)
    assert dup.status_code == 409
    bad = client.post(f"{API}/semesters", json={"batch_id": ids["batch"], "number": 13}, headers=hod_h)
    assert bad.status_code == 422
    dates = client.post(f"{API}/semesters", json={"batch_id": ids["batch"], "number": 8,
                                                  "start_date": "2026-09-01", "end_date": "2026-01-01"},
                        headers=hod_h)
    assert dates.status_code == 422


def test_hod_cannot_add_semester_to_other_department(client, hod_h, ee):
    res = client.post(f"{API}/semesters", json={"batch_id": ee["batch"], "number": 3}, headers=hod_h)
    assert res.status_code == 404


# ── Sections ──────────────────────────────────────────────────────────────


def test_section_crud(client, hod_h, ids, audit):
    res = client.post(f"{API}/sections", json={"semester_id": ids["semester"], "name": " c ", "capacity": 40},
                      headers=hod_h)
    assert res.status_code == 201, res.text
    section = res.json()
    assert section["name"] == "C" and section["batch_id"] == ids["batch"] and section["semester_number"] == 6
    res = client.patch(f"{API}/sections/{section['id']}", json={"capacity": 45, "is_active": False}, headers=hod_h)
    assert res.json()["capacity"] == 45 and res.json()["is_active"] is False
    assert audit("section.created") and audit("section.updated")


def test_section_duplicates_and_chain_validation(client, hod_h, ids, ee):
    assert client.post(f"{API}/sections", json={"semester_id": ids["semester"], "name": "a"},
                       headers=hod_h).status_code == 409
    rename = client.patch(f"{API}/sections/{ids['section_b']}", json={"name": "A"}, headers=hod_h)
    assert rename.status_code == 409
    mismatch = client.post(f"{API}/sections", json={"semester_id": ids["semester"], "batch_id": ee["batch"],
                                                    "name": "Z"}, headers=hod_h)
    assert mismatch.status_code == 422
    assert client.post(f"{API}/sections", json={"semester_id": ee["semester"], "name": "Z"},
                       headers=hod_h).status_code == 404


def test_section_list_filters(client, hod_h, ids):
    res = client.get(f"{API}/sections", params={"semester_id": ids["semester"]}, headers=hod_h).json()
    assert {s["name"] for s in res["items"]} == {"A", "B"}
    student_counts = {s["name"]: s["student_count"] for s in res["items"]}
    assert student_counts["A"] == 2  # approved + pending seeded students


# ── Courses ───────────────────────────────────────────────────────────────


def test_course_crud_and_code_normalisation(client, hod_h, ids, audit):
    res = client.post(f"{API}/courses", json={"code": "  comp-02735 ", "title": "Digital  System Design",
                                              "credit_hours": 3}, headers=hod_h)
    assert res.status_code == 201, res.text
    course = res.json()
    assert course["code"] == "COMP-02735" and course["title"] == "Digital System Design"
    assert course["department_id"] == ids["cse"]
    res = client.patch(f"{API}/courses/{course['id']}", json={"is_lab": True, "credit_hours": 1}, headers=hod_h)
    assert res.json()["is_lab"] is True
    assert audit("course.created")[0].new_value["code"] == "COMP-02735"
    assert audit("course.updated")[0].new_value == {"credit_hours": 1, "is_lab": True}


def test_course_code_unique_within_department_only(client, hod_h, ee_hod_h):
    assert client.post(f"{API}/courses", json={"code": "cs-321", "title": "Duplicate"},
                       headers=hod_h).status_code == 409
    other = client.post(f"{API}/courses", json={"code": "CS-321", "title": "Same code, other dept"},
                        headers=ee_hod_h)
    assert other.status_code == 201


def test_course_isolation_and_filters(client, hod_h, ids, ee):
    assert client.patch(f"{API}/courses/{ee['course']}", json={"title": "Changed"}, headers=hod_h).status_code == 404
    assert client.post(f"{API}/courses", json={"code": "X-1", "title": "Sneaky", "department_id": ee["dept"]},
                       headers=hod_h).status_code == 404
    client.patch(f"{API}/courses/{ids['courses']['MA-301']}", json={"is_active": False}, headers=hod_h)
    active = client.get(f"{API}/courses", params={"is_active": True}, headers=hod_h).json()
    assert "MA-301" not in {c["code"] for c in active["items"]}
    found = client.get(f"{API}/courses", params={"q": "numerical"}, headers=hod_h).json()
    assert [c["code"] for c in found["items"]] == ["MA-301"]


def test_course_validation(client, hod_h):
    assert client.post(f"{API}/courses", json={"code": "!!", "title": "Bad"}, headers=hod_h).status_code == 422
    assert client.post(f"{API}/courses", json={"code": "OK-1", "title": "Too many credits", "credit_hours": 50},
                       headers=hod_h).status_code == 422


def test_pagination(client, hod_h):
    for i in range(5):
        client.post(f"{API}/courses", json={"code": f"PG-{i}", "title": f"Paged {i}"}, headers=hod_h)
    page = client.get(f"{API}/courses", params={"page": 2, "page_size": 3}, headers=hod_h).json()
    assert page["total"] == 9 and page["page"] == 2 and len(page["items"]) == 3


def test_blank_semester_name_uses_default(client, hod_h, ids):
    res = client.post(f"{API}/semesters", json={"batch_id": ids["batch"], "number": 8, "name": "   "}, headers=hod_h)
    assert res.status_code == 201 and res.json()["name"] == "Semester 8"
    res = client.patch(f"{API}/semesters/{res.json()['id']}", json={"name": "  "}, headers=hod_h)
    assert res.status_code == 200 and res.json()["name"] == "Semester 8"
