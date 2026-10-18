"""Student "My Attendance": own subjects, finalized-only counts, history and access rules."""

import pytest
from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.models import TeacherCourseAssignment
from backend.app.services.attendance_policy import summarize
from tests.conftest import STUDENT_EMAIL
from tests.test_attendance import API, cls, finalize, mark, start, teacher_h  # noqa: F401

ME = "F23CSE01"  # the seeded student (STUDENT_EMAIL), enrolled in all four CSE subjects


def _take(client, teacher_h, assignment, number, my_status, finalized=True):
    """Start session `number`, mark ME with my_status (everyone else present), optionally finalize."""
    s = start(client, teacher_h, assignment, number=number).json()["session"]
    statuses = [my_status if r["registration_no"] == ME else "present" for r in s["records"]]
    s = mark(client, teacher_h, s, statuses).json()
    if finalized:
        assert finalize(client, teacher_h, s).status_code == 200
    return s


@pytest.fixture()
def student_h(login):
    return login(STUDENT_EMAIL)


@pytest.fixture()
def history(client, teacher_h, cls, ids, db_session):
    """CS-321: P, A, L, E, P finalized + one draft (absent) + one cancelled (absent).
    CS-321L: one finalized absence."""
    for number, status in enumerate(["present", "absent", "late", "excused", "present"], start=1):
        _take(client, teacher_h, cls["assignment"], number, status)
    _take(client, teacher_h, cls["assignment"], 6, "absent", finalized=False)  # draft
    cancelled = _take(client, teacher_h, cls["assignment"], 7, "absent", finalized=False)
    assert client.post(f"{API}/attendance/sessions/{cancelled['id']}/cancel", headers=teacher_h,
                       json={"version": cancelled["version"], "reason": "Wrong slot"}).status_code == 200
    with db_session() as db:
        lab = db.scalar(select(TeacherCourseAssignment.id).where(
            TeacherCourseAssignment.course_id == ids["courses"]["CS-321L"]))
    _take(client, teacher_h, lab, 1, "absent")
    return {"lab": lab}


def _subject(data, code):
    return next(s for s in data["subjects"] if s["course_code"] == code)


def test_student_sees_own_enrolled_subjects_with_counts(client, student_h, history):
    data = client.get(f"{API}/student/attendance", headers=student_h).json()
    assert {s["course_code"] for s in data["subjects"]} == {"CS-321", "CS-321L", "MA-301", "CS-341"}
    assert data["threshold"] == settings.LOW_ATTENDANCE_THRESHOLD

    cs = _subject(data, "CS-321")
    assert cs["course_title"] == "Digital System Design" and cs["section_name"] == "A"
    assert cs["teacher_names"] == ["Engr. Bilal Ahmed"]
    # Draft (#6) and cancelled (#7) absences never count.
    assert (cs["present"], cs["absent"], cs["late"], cs["excused"]) == (2, 1, 1, 1)
    assert cs["total_classes"] == 5
    expected = summarize({"present": 2, "absent": 1, "late": 1, "excused": 1})
    assert cs["percentage"] == expected.percentage and cs["conducted"] == expected.conducted
    assert cs["attended"] == expected.attended

    lab = _subject(data, "CS-321L")
    assert (lab["total_classes"], lab["absent"], lab["percentage"]) == (1, 1, 0.0)
    assert lab["low_attendance"] is True


def test_zero_finalized_sessions_is_na(client, student_h, teacher_h, cls):
    _take(client, teacher_h, cls["assignment"], 1, "absent", finalized=False)  # draft only
    data = client.get(f"{API}/student/attendance", headers=student_h).json()
    for subject in data["subjects"]:
        assert subject["total_classes"] == 0 and subject["percentage"] is None
        assert subject["low_attendance"] is False
    assert _subject(data, "MA-301")["teacher_names"] == []  # no teacher assigned yet
    detail = client.get(f"{API}/student/attendance/subjects/{cls['course']}", headers=student_h).json()
    assert detail["records"] == [] and detail["subject"]["percentage"] is None


def test_subject_detail_is_newest_first_and_minimal(client, student_h, history, cls):
    res = client.get(f"{API}/student/attendance/subjects/{cls['course']}", headers=student_h)
    assert res.status_code == 200
    detail = res.json()
    assert [r["session_number"] for r in detail["records"]] == [5, 4, 3, 2, 1]  # no draft #6, no cancelled #7
    assert [r["status"] for r in detail["records"]] == ["present", "excused", "late", "absent", "present"]
    for record in detail["records"]:
        assert set(record) == {"session_date", "session_number", "status"}  # no photos/confidence/notes/ids
    assert detail["subject"]["course_code"] == "CS-321" and detail["subject"]["total_classes"] == 5


def test_low_attendance_uses_configured_threshold(client, student_h, history, monkeypatch):
    # CS-321 is at 75.0% under the default policy.
    monkeypatch.setattr(settings, "LOW_ATTENDANCE_THRESHOLD", 75.0)
    data = client.get(f"{API}/student/attendance", headers=student_h).json()
    assert _subject(data, "CS-321")["percentage"] == 75.0 and _subject(data, "CS-321")["low_attendance"] is False
    monkeypatch.setattr(settings, "LOW_ATTENDANCE_THRESHOLD", 80.0)
    data = client.get(f"{API}/student/attendance", headers=student_h).json()
    assert data["threshold"] == 80.0 and _subject(data, "CS-321")["low_attendance"] is True
    # The dashboard card uses the same student threshold.
    dash = client.get(f"{API}/dashboard/student/subjects", headers=student_h).json()
    assert dash["threshold"] == 80.0 and _subject(dash, "CS-321")["low_attendance"] is True


def test_student_sees_only_own_attendance(client, student_h, history, cls, login):
    other_h = login("s4@test.edu", "Student@123")  # F23CSE04: present in every CS-321 session
    other = _subject(client.get(f"{API}/student/attendance", headers=other_h).json(), "CS-321")
    assert (other["present"], other["absent"], other["late"], other["excused"]) == (5, 0, 0, 0)
    # A student_id parameter is simply ignored: identity comes from the token.
    mine = client.get(f"{API}/student/attendance", params={"student_id": 999}, headers=student_h).json()
    assert _subject(mine, "CS-321")["present"] == 2
    detail = client.get(f"{API}/student/attendance/subjects/{cls['course']}", params={"student_id": 999},
                        headers=other_h).json()
    assert {r["status"] for r in detail["records"]} == {"present"}


def test_unenrolled_subject_cannot_be_queried(client, student_h, hod_h, teacher_h, history, ids, ee, db_session):
    new_course = client.post(f"{API}/courses", json={"code": "CS-399", "title": "Elective"}, headers=hod_h).json()
    for course_id in (new_course["id"], ee["course"], 999999):
        assert client.get(f"{API}/student/attendance/subjects/{course_id}", headers=student_h).status_code == 404
    # Removing the enrollment hides the subject (and its history) from the student.
    enrollments = client.get(f"{API}/enrollments", params={"assignment_id": history["lab"]}, headers=teacher_h).json()
    mine = next(e for e in enrollments["items"] if e["registration_no"] == ME)
    assert client.delete(f"{API}/enrollments/{mine['id']}", headers=teacher_h).status_code == 204
    data = client.get(f"{API}/student/attendance", headers=student_h).json()
    assert "CS-321L" not in {s["course_code"] for s in data["subjects"]}
    assert client.get(f"{API}/student/attendance/subjects/{ids['courses']['CS-321L']}",
                      headers=student_h).status_code == 404


def test_staff_cannot_use_student_endpoints(client, hod_h, admin_h, teacher_h, ids):
    for headers in (hod_h, admin_h, teacher_h):
        assert client.get(f"{API}/student/attendance", headers=headers).status_code == 403
        assert client.get(f"{API}/student/attendance/subjects/{ids['courses']['CS-321']}",
                          headers=headers).status_code == 403
    assert client.get(f"{API}/student/attendance").status_code == 401
