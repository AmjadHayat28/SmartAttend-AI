"""Delete Attendance: permanently delete ONE finalized session (and only that session).

Option A (edit one student's record) is covered in test_attendance.py. Here: the hard delete of a
whole session — what is removed, what is kept (a minimal audit event), exact-slot scope,
permissions (only the session's own teacher within the window — never HODs or the super admin).
"""

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from backend.app.models import (
    AttendanceModification,
    AttendanceRecognitionFace,
    AttendanceRecognitionRun,
    AttendanceRecord,
    AttendanceSession,
    AttendanceSessionImage,
    AuditLog,
    Student,
    StudentCourseEnrollment,
    TeacherCourseAssignment,
)
from tests.conftest import STUDENT_EMAIL
from tests.fake_face_engine import with_similarity
from tests.test_attendance import API, cls, ee_class, finalize, mark, start, upload_photo  # noqa: F401
from tests.test_recognition import classroom_photo, rc, run, teacher_h  # noqa: F401

REASON = "Attendance was taken incorrectly."


def _final(client, headers, assignment, statuses=("present",) * 5, day=None, number=1):
    s = start(client, headers, assignment, number=number, **({"day": day} if day else {})).json()["session"]
    s = mark(client, headers, s, list(statuses)).json()
    res = finalize(client, headers, s)
    assert res.status_code == 200, res.text
    return res.json()


def delete(client, headers, session, reason=REASON, **extra):
    return client.post(f"{API}/attendance/sessions/{session['id']}/delete", headers=headers,
                       json={"reason": reason, **extra})


def get(client, headers, session_id):
    return client.get(f"{API}/attendance/sessions/{session_id}", headers=headers)


def _rows(db_session, model, column, session_id):
    with db_session() as db:
        return db.scalar(select(func.count()).select_from(model).where(column == session_id))


@pytest.fixture()
def ee_final(client, ee_class):
    s = mark(client, ee_class["teacher_h"], ee_class["session"], ["present"]).json()
    return finalize(client, ee_class["teacher_h"], s).json()


# ── What a delete removes, and what it keeps ──────────────────────────────


def test_teacher_deletes_own_session_with_everything_that_belongs_to_it(
        client, teacher_h, rc, fake_face_engine, db_session, isolated_uploads, audit):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600,
                    [with_similarity(rc["vec"]["F23CSE01"], 0.8, 1)])
    assert run(client, teacher_h, get(client, teacher_h, s["id"]).json()).status_code == 200
    s = get(client, teacher_h, s["id"]).json()
    s = mark(client, teacher_h, s, [r["status"] or "absent" for r in s["records"]]).json()
    final = finalize(client, teacher_h, s).json()
    corrected = client.post(f"{API}/attendance/records/{final['records'][1]['id']}/correct", headers=teacher_h,
                            json={"status": "present", "reason": "Student was present but AI missed him"})
    assert corrected.status_code == 200
    sid = final["id"]
    with db_session() as db:
        run_ids = list(db.scalars(select(AttendanceRecognitionRun.id).where(AttendanceRecognitionRun.session_id == sid)))
        assert run_ids and db.scalar(select(func.count(AttendanceRecognitionFace.id))
                                     .where(AttendanceRecognitionFace.run_id.in_(run_ids)))
        assert db.scalar(select(func.count(AttendanceModification.id))) == 1
    assert list(isolated_uploads.rglob("*.jpg"))
    assert final["can_delete"] is True

    res = delete(client, teacher_h, final)
    assert res.status_code == 204, res.text

    assert get(client, teacher_h, sid).status_code == 404
    for model, column in ((AttendanceSession, AttendanceSession.id), (AttendanceRecord, AttendanceRecord.session_id),
                          (AttendanceSessionImage, AttendanceSessionImage.session_id),
                          (AttendanceRecognitionRun, AttendanceRecognitionRun.session_id)):
        assert _rows(db_session, model, column, sid) == 0, model.__name__
    with db_session() as db:
        assert db.scalar(select(func.count(AttendanceRecognitionFace.id))) == 0
        assert db.scalar(select(func.count(AttendanceModification.id))) == 0
        # Students and enrollments are untouched.
        assert db.scalar(select(func.count(Student.id))) >= 5
        assert db.scalar(select(func.count(StudentCourseEnrollment.id))) > 0
    assert not list(isolated_uploads.rglob("*.jpg"))  # classroom photo files removed
    assert not (isolated_uploads / "attendance" / str(sid)).exists()

    # A minimal audit event remains: who deleted which session, and why — no student data.
    entry = audit("attendance.session_deleted")[0]
    assert entry.entity == "attendance_session" and entry.entity_id == str(sid) and entry.timestamp
    assert entry.old_value == {
        "session_id": sid, "course_id": final["course_id"], "course_code": "CS-321",
        "course_title": final["course_title"], "section_id": final["section_id"], "section_name": "A",
        "session_date": final["session_date"], "session_number": 1, "teacher_id": final["teacher_id"],
    }
    assert entry.new_value == {"reason": REASON, "deleted_by_role": "teacher"}
    dump = json.dumps([entry.old_value, entry.new_value])
    assert "F23CSE" not in dump and "present" not in dump


def test_same_slot_is_free_again_and_no_draft_is_created(client, teacher_h, cls, db_session):
    final = _final(client, teacher_h, cls["assignment"])
    assert start(client, teacher_h, cls["assignment"]).status_code == 409  # slot taken while it exists
    assert delete(client, teacher_h, final).status_code == 204
    with db_session() as db:
        assert db.scalar(select(func.count(AttendanceSession.id))) == 0  # nothing created automatically
    fresh = start(client, teacher_h, cls["assignment"])
    assert fresh.status_code == 201 and fresh.json()["session"]["status"] == "draft"
    assert fresh.json()["resumed"] is False


def test_only_the_selected_session_is_deleted(client, teacher_h, cls, db_session):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    previous = _final(client, teacher_h, cls["assignment"], day=yesterday)
    s1 = _final(client, teacher_h, cls["assignment"], number=1)
    s2 = _final(client, teacher_h, cls["assignment"], ["absent"] * 5, number=2)
    s3 = _final(client, teacher_h, cls["assignment"], number=3)
    with db_session() as db:
        enrollments = db.scalar(select(func.count(StudentCourseEnrollment.id)))
        assignments = db.scalar(select(func.count(TeacherCourseAssignment.id)))

    assert delete(client, teacher_h, s2).status_code == 204

    assert get(client, teacher_h, s2["id"]).status_code == 404
    for untouched in (previous, s1, s3):
        now = get(client, teacher_h, untouched["id"]).json()
        assert now["status"] == "finalized" and now["version"] == untouched["version"]
        assert now["records"] == untouched["records"]
    with db_session() as db:
        assert db.scalar(select(func.count(StudentCourseEnrollment.id))) == enrollments
        assert db.scalar(select(func.count(TeacherCourseAssignment.id))) == assignments
        assert db.scalar(select(func.count(AttendanceRecord.id))) == 15
    listed = client.get(f"{API}/attendance/sessions", headers=teacher_h).json()
    assert {i["id"] for i in listed["items"]} == {previous["id"], s1["id"], s3["id"]}
    # Only session 2's slot is free.
    assert start(client, teacher_h, cls["assignment"], number=1).status_code == 409
    assert start(client, teacher_h, cls["assignment"], number=3).status_code == 409
    assert start(client, teacher_h, cls["assignment"], number=2).status_code == 201


def test_deleted_session_no_longer_counts(client, teacher_h, hod_h, cls, login):
    _final(client, teacher_h, cls["assignment"], ["present"] * 5, number=1)
    wrong = _final(client, teacher_h, cls["assignment"], ["absent"] * 5, number=2)

    def figures():
        student = client.get(f"{API}/dashboard/student/subjects", headers=login(STUDENT_EMAIL)).json()
        card = next(c for c in student["subjects"] if c["course_code"] == "CS-321")
        cs321 = next(c for c in client.get(f"{API}/attendance/classes", headers=teacher_h).json()
                     if c["course_code"] == "CS-321")
        hod = client.get(f"{API}/dashboard/hod", headers=hod_h).json()
        return card["percentage"], card["conducted"], cs321["attendance_percentage"], hod["today_attendance_pct"]

    assert figures() == (50.0, 2, 50.0, 50.0)
    delete(client, teacher_h, wrong)
    assert figures() == (100.0, 1, 100.0, 100.0)


# ── Permissions ───────────────────────────────────────────────────────────


def test_teacher_cannot_delete_another_teachers_attendance(client, teacher_h, hod_h, cls, ee_final, login):
    assert delete(client, teacher_h, ee_final).status_code == 404  # other department's teacher
    client.post(f"{API}/teachers", headers=hod_h, json={
        "full_name": "Co Teacher", "email": "co@test.edu", "password": "Teach@1234", "employee_id": "EMP-T-777"})
    co_id = client.get(f"{API}/teachers", params={"q": "EMP-T-777"}, headers=hod_h).json()["items"][0]["id"]
    client.post(f"{API}/assignments", headers=hod_h, json={
        "teacher_id": co_id, "course_id": cls["course"], "section_id": cls["section"]})
    final = _final(client, teacher_h, cls["assignment"])
    assert delete(client, login("co@test.edu", "Teach@1234"), final).status_code == 404  # same class, not theirs
    assert get(client, teacher_h, final["id"]).json()["status"] == "finalized"


def test_teacher_no_longer_assigned_cannot_delete(client, teacher_h, hod_h, cls):
    final = _final(client, teacher_h, cls["assignment"])
    client.delete(f"{API}/assignments/{cls['assignment']}", headers=hod_h)
    res = delete(client, teacher_h, final)
    assert res.status_code == 403 and "still assigned" in res.json()["detail"]


def test_teacher_blocked_after_window_and_attendance_locked(client, teacher_h, hod_h, cls, db_session):
    final = _final(client, teacher_h, cls["assignment"])
    with db_session() as db:  # finalized 25 hours ago (ATTENDANCE_TEACHER_CORRECTION_HOURS=24)
        db.get(AttendanceSession, final["id"]).finalized_at = datetime.now(UTC) - timedelta(hours=25)
        db.commit()
    assert get(client, teacher_h, final["id"]).json()["can_delete"] is False
    res = delete(client, teacher_h, final)
    assert res.status_code == 403 and "locked" in res.json()["detail"]
    # Locked: the HOD has no override either.
    assert delete(client, hod_h, final, reason="Duplicate session entered by mistake").status_code == 403
    assert get(client, teacher_h, final["id"]).json()["status"] == "finalized"


def test_hods_cannot_delete_attendance(client, hod_h, ee_final, ee_class):
    for hod in (hod_h, ee_class["hod_h"]):  # any HOD, including the session's own department
        assert delete(client, hod, ee_final).status_code == 403
    assert get(client, ee_class["teacher_h"], ee_final["id"]).json()["status"] == "finalized"
    assert delete(client, ee_class["teacher_h"], ee_final).status_code == 204  # its own teacher can


def test_super_admin_and_students_cannot_delete(client, admin_h, teacher_h, cls, login):
    final = _final(client, teacher_h, cls["assignment"])
    assert delete(client, admin_h, final).status_code == 403
    assert delete(client, login(STUDENT_EMAIL), final).status_code == 403
    assert get(client, teacher_h, final["id"]).status_code == 200


# ── Validation and safety ─────────────────────────────────────────────────


def test_reason_is_mandatory(client, teacher_h, cls):
    final = _final(client, teacher_h, cls["assignment"])
    for reason in (None, "", "    ", "abc"):
        assert delete(client, teacher_h, final, reason=reason).status_code == 422, reason
    no_reason = client.post(f"{API}/attendance/sessions/{final['id']}/delete", headers=teacher_h, json={})
    assert no_reason.status_code == 422
    assert get(client, teacher_h, final["id"]).json()["status"] == "finalized"


def test_drafts_and_stale_tabs(client, teacher_h, cls):
    draft = start(client, teacher_h, cls["assignment"]).json()["session"]
    res = delete(client, teacher_h, draft)
    assert res.status_code == 409 and "Discard" in res.json()["detail"]
    final = _final(client, teacher_h, cls["assignment"], number=2)
    assert delete(client, teacher_h, final, version=final["version"] - 1).status_code == 409
    assert delete(client, teacher_h, final, version=final["version"]).status_code == 204
    assert delete(client, teacher_h, final).status_code == 404  # already gone


def test_failed_delete_rolls_back_and_keeps_files(client, teacher_h, cls, db_session, isolated_uploads, monkeypatch):
    s = start(client, teacher_h, cls["assignment"]).json()["session"]
    upload_photo(client, teacher_h, s["id"])
    s = mark(client, teacher_h, get(client, teacher_h, s["id"]).json(), ["present"] * 5).json()
    final = finalize(client, teacher_h, s).json()

    from backend.app.services import attendance_service

    def boom(*args, **kwargs):
        raise RuntimeError("audit storage unavailable")

    monkeypatch.setattr(attendance_service, "record_audit", boom)
    with pytest.raises(RuntimeError):
        delete(client, teacher_h, final)
    monkeypatch.undo()
    assert get(client, teacher_h, final["id"]).json()["status"] == "finalized"
    assert _rows(db_session, AttendanceRecord, AttendanceRecord.session_id, final["id"]) == 5
    assert _rows(db_session, AttendanceSessionImage, AttendanceSessionImage.session_id, final["id"]) == 1
    assert len(list(isolated_uploads.rglob("*.jpg"))) == 1  # files are only removed after a commit
    with db_session() as db:
        assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "attendance.session_deleted")) == 0
