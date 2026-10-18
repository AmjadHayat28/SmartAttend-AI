"""Phase 5: teacher attendance sessions (manual marking only — no recognition)."""

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.models import AttendanceModification, AttendanceSession, AuditLog, TeacherCourseAssignment
from backend.app.services.attendance_policy import AttendanceSummary, summarize
from tests import imaging
from tests.conftest import STUDENT_EMAIL, TEACHER_EMAIL

API = "/api/v1"
TODAY = date.today().isoformat()


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def teacher_h(login):
    return login(TEACHER_EMAIL)


@pytest.fixture()
def cls(client, hod_h, teacher_h, ids, db_session):
    """CS-321 / Section A with 5 enrolled students (4 active + 1 pending) and its assignment id.
    The HOD creates the students; the class's teacher enrolls the section."""
    for i in range(4, 7):
        client.post(f"{API}/students", headers=hod_h, json={
            "full_name": f"Student {i}", "email": f"s{i}@test.edu", "password": "Student@123",
            "registration_no": f"F23CSE0{i}", "batch_id": ids["batch"], "semester_id": ids["semester"],
            "section_id": ids["section_a"]})
    with db_session() as db:
        assignment = db.scalar(select(TeacherCourseAssignment.id).where(
            TeacherCourseAssignment.course_id == ids["courses"]["CS-321"],
            TeacherCourseAssignment.section_id == ids["section_a"]))
    res = client.post(f"{API}/enrollments/bulk", headers=teacher_h, json={"assignment_id": assignment})
    assert res.status_code == 200
    return {"assignment": assignment, "course": ids["courses"]["CS-321"], "section": ids["section_a"]}


def start(client, headers, assignment, day=TODAY, number=1):
    return client.post(f"{API}/attendance/sessions", headers=headers,
                       json={"assignment_id": assignment, "session_date": day, "session_number": number})


def mark(client, headers, session, statuses, version=None):
    """statuses: list aligned with session['records'] order."""
    changes = [{"record_id": r["id"], "status": s} for r, s in zip(session["records"], statuses)]
    return client.patch(f"{API}/attendance/sessions/{session['id']}/records", headers=headers,
                        json={"version": session["version"] if version is None else version, "changes": changes})


def finalize(client, headers, session):
    return client.post(f"{API}/attendance/sessions/{session['id']}/finalize", headers=headers,
                       json={"version": session["version"]})


def upload_photo(client, headers, session_id, img=None):
    data = imaging.jpeg(img if img is not None else imaging.two_faces())
    return client.post(f"{API}/attendance/sessions/{session_id}/images", headers=headers,
                       files={"file": ("class.jpg", data, "image/jpeg")})


@pytest.fixture()
def ee_class(client, ee_hod_h, ee, login):
    """EE: a HOD, the EE teacher assigned to EE-101/A with an enrolled student, and a draft session."""
    assignment = client.post(f"{API}/assignments", headers=ee_hod_h, json={
        "teacher_id": ee["teacher"], "course_id": ee["course"], "section_id": ee["section"]}).json()
    ee_teacher_h = login("teacher.ee@test.edu")
    client.post(f"{API}/enrollments", headers=ee_teacher_h,
                json={"assignment_id": assignment["id"], "student_id": ee["student"]})
    session = start(client, ee_teacher_h, assignment["id"]).json()["session"]
    return {"assignment": assignment["id"], "session": session, "teacher_h": ee_teacher_h, "hod_h": ee_hod_h}


# ── Access rules ──────────────────────────────────────────────────────────


def test_teacher_sees_only_assigned_classes(client, teacher_h, cls, login, hod_h):
    classes = client.get(f"{API}/attendance/classes", headers=teacher_h).json()
    assert {c["course_code"] for c in classes} == {"CS-321", "CS-321L"}
    cs321 = next(c for c in classes if c["course_code"] == "CS-321")
    assert cs321["enrolled_count"] == 5 and cs321["batch_name"] == "F23" and cs321["semester_number"] == 6
    assert cs321["attendance_percentage"] is None and cs321["open_draft_session_id"] is None
    for headers in (hod_h, login(STUDENT_EMAIL)):
        assert client.get(f"{API}/attendance/classes", headers=headers).status_code == 403


def test_teacher_cannot_start_unassigned_or_inactive_class(client, teacher_h, hod_h, cls, ee_class):
    assert start(client, teacher_h, ee_class["assignment"]).status_code == 404  # other department/teacher
    assert start(client, teacher_h, 999999).status_code == 404
    client.delete(f"{API}/assignments/{cls['assignment']}", headers=hod_h)
    assert start(client, teacher_h, cls["assignment"]).status_code == 404  # assignment removed


def test_date_and_session_number_validation(client, teacher_h, cls):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert "future" in start(client, teacher_h, cls["assignment"], day=tomorrow).json()["detail"]
    too_old = (date.today() - timedelta(days=settings.ATTENDANCE_MAX_BACKDATE_DAYS + 1)).isoformat()
    assert start(client, teacher_h, cls["assignment"], day=too_old).status_code == 422
    assert start(client, teacher_h, cls["assignment"], number=settings.ATTENDANCE_MAX_SESSIONS_PER_DAY + 1).status_code == 422
    assert start(client, teacher_h, cls["assignment"], number=0).status_code == 422


def test_empty_class_cannot_start(client, teacher_h, ids, db_session):
    with db_session() as db:
        lab = db.scalar(select(TeacherCourseAssignment.id).where(
            TeacherCourseAssignment.course_id == ids["courses"]["CS-321L"]))
    # CS-321L: only F23CSE01 is enrolled by the seed, so this works…
    assert start(client, teacher_h, lab).status_code == 201


# ── Draft lifecycle ───────────────────────────────────────────────────────


def test_create_and_resume_draft(client, teacher_h, cls, audit):
    res = start(client, teacher_h, cls["assignment"])
    assert res.status_code == 201
    body = res.json()
    session = body["session"]
    assert body["resumed"] is False and session["status"] == "draft" and session["version"] == 1
    assert session["can_edit"] is True and session["summary"]["total"] == 5
    assert session["summary"]["unmarked"] == 5  # records start unmarked (safer than defaulting to Absent)
    assert [r["registration_no"] for r in session["records"]] == sorted(r["registration_no"] for r in session["records"])
    assert audit("attendance.session_created")[0].new_value["roster_size"] == 5

    again = start(client, teacher_h, cls["assignment"])
    assert again.status_code == 200 and again.json()["resumed"] is True
    assert again.json()["session"]["id"] == session["id"]
    classes = client.get(f"{API}/attendance/classes", headers=teacher_h).json()
    assert next(c for c in classes if c["course_code"] == "CS-321")["open_draft_session_id"] == session["id"]


def test_mark_statuses_notes_and_summary(client, teacher_h, cls, audit):
    session = start(client, teacher_h, cls["assignment"]).json()["session"]
    res = mark(client, teacher_h, session, ["present", "present", "absent", "late", "excused"])
    assert res.status_code == 200
    updated = res.json()
    assert updated["version"] == 2
    assert {k: updated["summary"][k] for k in ("present", "absent", "late", "excused", "unmarked")} == \
        {"present": 2, "absent": 1, "late": 1, "excused": 1, "unmarked": 0}
    note = client.patch(f"{API}/attendance/sessions/{session['id']}/records", headers=teacher_h, json={
        "version": 2, "changes": [{"record_id": session["records"][3]["id"], "note": "  Arrived 15  minutes late "}]})
    assert note.json()["records"][3]["note"] == "Arrived 15 minutes late"
    assert note.json()["records"][3]["status"] == "late"  # note-only change keeps the status
    assert audit("attendance.records_updated")


def test_stale_version_conflict(client, teacher_h, cls):
    session = start(client, teacher_h, cls["assignment"]).json()["session"]
    assert mark(client, teacher_h, session, ["present"]).status_code == 200  # tab A: version 1 → 2
    stale = mark(client, teacher_h, session, ["absent"])  # tab B still holds version 1
    assert stale.status_code == 409 and "another tab" in stale.json()["detail"]


def test_records_must_belong_to_the_session(client, teacher_h, cls, ids, db_session):
    session = start(client, teacher_h, cls["assignment"]).json()["session"]
    res = client.patch(f"{API}/attendance/sessions/{session['id']}/records", headers=teacher_h,
                       json={"version": 1, "changes": [{"record_id": 999999, "status": "present"}]})
    assert res.status_code == 422


def test_bulk_actions(client, teacher_h, cls, audit):
    session = start(client, teacher_h, cls["assignment"]).json()["session"]
    s = mark(client, teacher_h, session, ["late"]).json()
    s = client.post(f"{API}/attendance/sessions/{s['id']}/bulk", headers=teacher_h,
                    json={"version": s["version"], "action": "unmarked_absent"}).json()
    assert (s["summary"]["late"], s["summary"]["absent"], s["summary"]["unmarked"]) == (1, 4, 0)
    s = client.post(f"{API}/attendance/sessions/{s['id']}/bulk", headers=teacher_h,
                    json={"version": s["version"], "action": "all_present"}).json()
    assert s["summary"]["present"] == 5
    s = client.post(f"{API}/attendance/sessions/{s['id']}/bulk", headers=teacher_h,
                    json={"version": s["version"], "action": "reset"}).json()
    assert s["summary"]["unmarked"] == 5
    assert {e.new_value["action"] for e in audit("attendance.bulk_update")} == {"unmarked_absent", "all_present", "reset"}


def test_session_note(client, teacher_h, cls, audit):
    session = start(client, teacher_h, cls["assignment"]).json()["session"]
    res = client.patch(f"{API}/attendance/sessions/{session['id']}", headers=teacher_h,
                       json={"version": 1, "note": "Quiz conducted during first 20 minutes."})
    assert res.json()["note"] == "Quiz conducted during first 20 minutes." and res.json()["version"] == 2
    assert client.patch(f"{API}/attendance/sessions/{session['id']}", headers=teacher_h,
                        json={"version": 2, "note": "x" * 301}).status_code == 422
    assert audit("attendance.note_changed")[0].new_value["note"].startswith("Quiz")


# ── Finalization ──────────────────────────────────────────────────────────


def test_finalize_requires_everyone_marked_then_locks(client, teacher_h, cls, audit):
    session = start(client, teacher_h, cls["assignment"]).json()["session"]
    s = mark(client, teacher_h, session, ["present", "absent"]).json()
    res = finalize(client, teacher_h, s)
    assert res.status_code == 422 and "3 student(s) are not marked" in res.json()["detail"]
    s = client.post(f"{API}/attendance/sessions/{s['id']}/bulk", headers=teacher_h,
                    json={"version": s["version"], "action": "unmarked_absent"}).json()
    res = finalize(client, teacher_h, s)
    assert res.status_code == 200
    final = res.json()
    assert final["status"] == "finalized" and final["finalized_at"] and final["finalized_by_name"] == "Engr. Bilal Ahmed"
    assert final["can_edit"] is False and final["can_correct"] is True  # within the teacher window
    assert audit("attendance.session_finalized")[0].new_value == {"total": 5, "present": 1, "absent": 4,
                                                                "late": 0, "excused": 0}
    # Locked for normal edits.
    assert mark(client, teacher_h, final, ["absent"]).status_code == 409
    assert client.post(f"{API}/attendance/sessions/{s['id']}/bulk", headers=teacher_h,
                       json={"version": final["version"], "action": "reset"}).status_code == 409
    assert upload_photo(client, teacher_h, s["id"]).status_code == 409
    assert client.post(f"{API}/attendance/sessions/{s['id']}/cancel", headers=teacher_h,
                       json={"version": final["version"]}).status_code == 409


def test_duplicate_finalized_session_prevented(client, teacher_h, cls):
    session = start(client, teacher_h, cls["assignment"]).json()["session"]
    s = client.post(f"{API}/attendance/sessions/{session['id']}/bulk", headers=teacher_h,
                    json={"version": 1, "action": "all_present"}).json()
    finalize(client, teacher_h, s)
    dup = start(client, teacher_h, cls["assignment"])
    assert dup.status_code == 409
    assert dup.json()["detail"] == "Attendance for this class, subject, date and session already exists."
    assert start(client, teacher_h, cls["assignment"], number=2).status_code == 201  # a second lecture is fine


def test_cancel_frees_the_slot(client, teacher_h, cls, audit):
    session = start(client, teacher_h, cls["assignment"]).json()["session"]
    res = client.post(f"{API}/attendance/sessions/{session['id']}/cancel", headers=teacher_h,
                      json={"version": 1, "reason": "Wrong date"})
    assert res.json()["status"] == "cancelled" and res.json()["cancel_reason"] == "Wrong date"
    fresh = start(client, teacher_h, cls["assignment"])
    assert fresh.status_code == 201 and fresh.json()["session"]["id"] != session["id"]
    assert audit("attendance.session_cancelled")


def test_second_teacher_cannot_take_over_or_see_draft(client, teacher_h, hod_h, ids, cls, login):
    client.post(f"{API}/teachers", headers=hod_h, json={
        "full_name": "Co Teacher", "email": "co@test.edu", "password": "Teach@1234", "employee_id": "EMP-T-777"})
    co_id = client.get(f"{API}/teachers", params={"q": "EMP-T-777"}, headers=hod_h).json()["items"][0]["id"]
    co_assignment = client.post(f"{API}/assignments", headers=hod_h, json={
        "teacher_id": co_id, "course_id": cls["course"], "section_id": cls["section"]}).json()["id"]
    co_h = login("co@test.edu", "Teach@1234")
    session = start(client, teacher_h, cls["assignment"]).json()["session"]
    res = start(client, co_h, co_assignment)
    assert res.status_code == 409 and "Another teacher" in res.json()["detail"]
    assert client.get(f"{API}/attendance/sessions/{session['id']}", headers=co_h).status_code == 404
    assert mark(client, co_h, session, ["present"]).status_code == 404


# ── Roster integrity ──────────────────────────────────────────────────────


def test_roster_snapshot_and_draft_sync(client, teacher_h, hod_h, ids, cls):
    final = start(client, teacher_h, cls["assignment"]).json()["session"]
    final = client.post(f"{API}/attendance/sessions/{final['id']}/bulk", headers=teacher_h,
                        json={"version": 1, "action": "all_present"}).json()
    finalize(client, teacher_h, final)
    draft = start(client, teacher_h, cls["assignment"], number=2).json()["session"]

    # A new student joins the class afterwards.
    new = client.post(f"{API}/students", headers=hod_h, json={
        "full_name": "Late Joiner", "email": "late@test.edu", "password": "Student@123", "registration_no": "F23CSE08",
        "batch_id": ids["batch"], "semester_id": ids["semester"], "section_id": ids["section_a"]}).json()
    res = client.post(f"{API}/enrollments", headers=teacher_h,
                      json={"assignment_id": cls["assignment"], "student_id": new["id"]})
    assert res.status_code == 201  # enrolled by the class's teacher

    old = client.get(f"{API}/attendance/sessions/{final['id']}", headers=teacher_h).json()
    assert old["summary"]["total"] == 5  # finalized roster unchanged
    resumed = start(client, teacher_h, cls["assignment"], number=2).json()
    assert resumed["resumed"] is True and resumed["added_to_roster"] == 1
    assert resumed["session"]["summary"]["total"] == 6 and resumed["session"]["id"] == draft["id"]


def test_roster_follows_teacher_managed_enrollments(client, teacher_h, hod_h, ids, cls):
    """A new session's roster is exactly the active enrollments the teacher maintains."""
    enrolled = client.get(f"{API}/enrollments", params={"assignment_id": cls["assignment"]}, headers=teacher_h).json()
    dropped = next(e for e in enrolled["items"] if e["registration_no"] == "F23CSE04")
    assert client.delete(f"{API}/enrollments/{dropped['id']}", headers=teacher_h).status_code == 204
    outsider = client.post(f"{API}/students", headers=hod_h, json={
        "full_name": "Other Section", "email": "b1@test.edu", "password": "Student@123", "registration_no": "F23CSE70",
        "batch_id": ids["batch"], "semester_id": ids["semester"], "section_id": ids["section_b"]}).json()
    joiner = client.post(f"{API}/students", headers=hod_h, json={
        "full_name": "Joiner", "email": "j1@test.edu", "password": "Student@123", "registration_no": "F23CSE71",
        "batch_id": ids["batch"], "semester_id": ids["semester"], "section_id": ids["section_a"]}).json()
    assert client.post(f"{API}/enrollments", headers=teacher_h,
                       json={"assignment_id": cls["assignment"], "student_id": joiner["id"]}).status_code == 201

    session = start(client, teacher_h, cls["assignment"]).json()["session"]
    roster = {r["registration_no"] for r in session["records"]}
    assert roster == {"F23CSE01", "F23CSE03", "F23CSE05", "F23CSE06", "F23CSE71"}
    assert outsider["registration_no"] not in roster


# ── Classroom photos ──────────────────────────────────────────────────────


def test_classroom_photos(client, teacher_h, hod_h, admin_h, cls, login, isolated_uploads, audit, monkeypatch):
    session = start(client, teacher_h, cls["assignment"]).json()["session"]
    res = upload_photo(client, teacher_h, session["id"])  # two faces: fine for a classroom photo
    assert res.status_code == 201, res.text
    image = res.json()["images"][0]
    assert image["image_url"] == f"/attendance/images/{image['id']}" and image["width"] == 1280
    files = sorted(p.relative_to(isolated_uploads).as_posix() for p in isolated_uploads.rglob("*.jpg"))
    assert len(files) == 1 and files[0].startswith(f"attendance/{session['id']}/")

    assert client.get(f"{API}{image['image_url']}", headers=admin_h).status_code == 403  # not an attendance role
    assert client.get(f"{API}{image['image_url']}", headers=hod_h).status_code == 403  # teacher-only
    for headers in (teacher_h,):
        got = client.get(f"{API}{image['image_url']}", headers=headers)
        assert got.status_code == 200 and got.content[:2] == b"\xff\xd8" and "no-store" in got.headers["cache-control"]
    assert client.get(f"{API}{image['image_url']}", headers=login(STUDENT_EMAIL)).status_code == 403
    assert client.get(f"{API}{image['image_url']}").status_code == 401

    assert upload_photo(client, teacher_h, session["id"], imaging.face(300)).status_code == 422  # too small
    corrupt = client.post(f"{API}/attendance/sessions/{session['id']}/images", headers=teacher_h,
                          files={"file": ("x.jpg", b"\xff\xd8 broken", "image/jpeg")})
    assert corrupt.status_code == 422
    monkeypatch.setattr(settings, "ATTENDANCE_MAX_PHOTOS", 2)
    assert upload_photo(client, teacher_h, session["id"], imaging.no_face()).status_code == 201
    over = upload_photo(client, teacher_h, session["id"])
    assert over.status_code == 409 and "at most 2" in over.json()["detail"]

    removed = client.delete(f"{API}/attendance/sessions/{session['id']}/images/{image['id']}", headers=teacher_h)
    assert removed.status_code == 200 and len(removed.json()["images"]) == 1
    assert len(list(isolated_uploads.rglob("*.jpg"))) == 1
    assert audit("attendance.photo_uploaded") and audit("attendance.photo_removed")

    s = client.post(f"{API}/attendance/sessions/{session['id']}/bulk", headers=teacher_h,
                    json={"version": removed.json()["version"], "action": "all_absent"}).json()
    final = finalize(client, teacher_h, s).json()
    remaining = final["images"][0]["id"]
    locked = client.delete(f"{API}/attendance/sessions/{session['id']}/images/{remaining}", headers=teacher_h)
    assert locked.status_code == 409  # read-only after finalization


def test_other_teachers_photo_and_session_access(client, hod_h, teacher_h, ee_class):
    ee_session = ee_class["session"]
    image = upload_photo(client, ee_class["teacher_h"], ee_session["id"]).json()["images"][0]
    assert client.get(f"{API}{image['image_url']}", headers=teacher_h).status_code == 404  # not their session
    assert client.get(f"{API}/attendance/sessions/{ee_session['id']}", headers=teacher_h).status_code == 404
    assert client.get(f"{API}{image['image_url']}", headers=ee_class["teacher_h"]).status_code == 200
    for hod in (hod_h, ee_class["hod_h"]):  # not even the session's own department HOD
        assert client.get(f"{API}{image['image_url']}", headers=hod).status_code == 403
        assert client.get(f"{API}/attendance/sessions/{ee_session['id']}", headers=hod).status_code == 403


# ── History and management views ──────────────────────────────────────────


def test_history_and_scoped_lists(client, teacher_h, hod_h, admin_h, cls, ee_class):
    s1 = start(client, teacher_h, cls["assignment"]).json()["session"]
    s1 = client.post(f"{API}/attendance/sessions/{s1['id']}/bulk", headers=teacher_h,
                     json={"version": 1, "action": "all_present"}).json()
    finalize(client, teacher_h, s1)
    start(client, teacher_h, cls["assignment"], number=2)

    mine = client.get(f"{API}/attendance/sessions", headers=teacher_h).json()
    assert mine["total"] == 2 and {i["status"] for i in mine["items"]} == {"draft", "finalized"}
    finalized = next(i for i in mine["items"] if i["status"] == "finalized")
    assert finalized["summary"]["present"] == 5 and finalized["summary"]["percentage"] == 100.0
    assert client.get(f"{API}/attendance/sessions", params={"status": "draft"}, headers=teacher_h).json()["total"] == 1

    assert ee_class["session"]["id"] not in {i["id"] for i in mine["items"]}  # never another teacher's
    assert client.get(f"{API}/attendance/sessions", headers=ee_class["teacher_h"]).json()["total"] == 1
    for headers in (hod_h, ee_class["hod_h"], admin_h):
        assert client.get(f"{API}/attendance/sessions", headers=headers).status_code == 403
    filtered = client.get(f"{API}/attendance/sessions", headers=teacher_h,
                          params={"course_id": cls["course"], "date_from": TODAY, "date_to": TODAY}).json()
    assert filtered["total"] == 2
    assert client.get(f"{API}/attendance/sessions", headers=teacher_h, params={"q": "digital"}).json()["total"] == 2


def test_history_hides_cancelled_sessions(client, teacher_h, cls, db_session):
    final = _finalized(client, teacher_h, cls)
    draft = start(client, teacher_h, cls["assignment"], number=2).json()["session"]
    gone = start(client, teacher_h, cls["assignment"], number=3).json()["session"]
    client.post(f"{API}/attendance/sessions/{gone['id']}/cancel", headers=teacher_h,
                json={"version": gone["version"], "reason": "Wrong session"})

    mine = client.get(f"{API}/attendance/sessions", headers=teacher_h).json()
    listed = {i["id"]: i["status"] for i in mine["items"]}
    assert gone["id"] not in listed  # absent, so the history UI has no row / View button for it
    assert listed == {final["id"]: "finalized", draft["id"]: "draft"} and mine["total"] == 2
    assert "cancelled" not in listed.values()
    # Filtering explicitly by status cannot surface it either.
    assert client.get(f"{API}/attendance/sessions", params={"status": "cancelled"}, headers=teacher_h).json()["total"] == 0
    assert client.get(f"{API}/attendance/sessions", params={"status": "finalized"}, headers=teacher_h).json()["total"] == 1
    assert client.get(f"{API}/attendance/sessions", params={"status": "draft"}, headers=teacher_h).json()["total"] == 1
    # The record itself is kept for audit.
    with db_session() as db:
        assert db.get(AttendanceSession, gone["id"]).status == "cancelled"


def test_students_cannot_list_sessions(client, login):
    assert client.get(f"{API}/attendance/sessions", headers=login(STUDENT_EMAIL)).status_code == 403


# ── Corrections ───────────────────────────────────────────────────────────


def _finalized(client, teacher_h, cls, statuses=("present",) * 5):
    s = start(client, teacher_h, cls["assignment"]).json()["session"]
    s = mark(client, teacher_h, s, list(statuses)).json()
    return finalize(client, teacher_h, s).json()


def test_teacher_correction_within_window(client, teacher_h, cls, db_session, audit):
    final = _finalized(client, teacher_h, cls)
    record = final["records"][0]
    assert client.post(f"{API}/attendance/records/{record['id']}/correct", headers=teacher_h,
                       json={"status": "absent", "reason": "x"}).status_code == 422  # reason required
    res = client.post(f"{API}/attendance/records/{record['id']}/correct", headers=teacher_h,
                      json={"status": "late", "reason": "Arrived after roll call"})
    assert res.status_code == 200
    body = res.json()
    assert body["records"][0]["status"] == "late" and body["records"][0]["corrected"] is True
    mod = body["modifications"][0]
    assert (mod["old_status"], mod["new_status"], mod["reason"], mod["modifier_role"]) == \
        ("present", "late", "Arrived after roll call", "teacher")
    with db_session() as db:
        assert db.scalar(select(AttendanceModification.reason)) == "Arrived after roll call"
    entry = audit("attendance.record_corrected")[0]
    assert entry.old_value["status"] == "present" and entry.new_value["status"] == "late"
    assert client.post(f"{API}/attendance/records/{record['id']}/correct", headers=teacher_h,
                       json={"status": "late", "reason": "same again"}).status_code == 400


def test_teacher_correction_window_closed(client, teacher_h, hod_h, cls, monkeypatch):
    final = _finalized(client, teacher_h, cls)
    monkeypatch.setattr(settings, "ATTENDANCE_TEACHER_CORRECTION_HOURS", 0)
    record = final["records"][0]
    res = client.post(f"{API}/attendance/records/{record['id']}/correct", headers=teacher_h,
                      json={"status": "absent", "reason": "Recount"})
    assert res.status_code == 403 and "locked" in res.json()["detail"]
    # Nobody else can correct it either: attendance belongs to the teacher alone.
    res = client.post(f"{API}/attendance/records/{record['id']}/correct", headers=hod_h,
                      json={"status": "excused", "note": "Medical leave", "reason": "Medical certificate received"})
    assert res.status_code == 403
    monkeypatch.undo()
    assert client.get(f"{API}/attendance/sessions/{final['id']}", headers=teacher_h).json()["records"][0]["status"] \
        == "present"


def test_correction_scope_and_drafts(client, teacher_h, hod_h, cls, ee_class, admin_h):
    draft = start(client, teacher_h, cls["assignment"]).json()["session"]
    assert client.post(f"{API}/attendance/records/{draft['records'][0]['id']}/correct", headers=teacher_h,
                       json={"status": "absent", "reason": "Not allowed on drafts"}).status_code == 409
    ee_record = ee_class["session"]["records"][0]["id"]
    assert client.post(f"{API}/attendance/records/{ee_record}/correct", headers=teacher_h,
                       json={"status": "absent", "reason": "Another teacher's class"}).status_code == 404
    for headers in (hod_h, ee_class["hod_h"], admin_h):
        assert client.post(f"{API}/attendance/records/{ee_record}/correct", headers=headers,
                           json={"status": "absent", "reason": "Not an attendance role"}).status_code == 403


# ── Attendance percentage policy ──────────────────────────────────────────


def test_policy_unit(monkeypatch):
    s = AttendanceSummary(present=6, absent=2, late=1, excused=1)
    monkeypatch.setattr(settings, "ATTENDANCE_LATE_WEIGHT", 1.0)
    monkeypatch.setattr(settings, "ATTENDANCE_EXCUSED_POLICY", "exclude")
    assert (s.attended, s.conducted, s.percentage) == (7, 9, 77.8)
    monkeypatch.setattr(settings, "ATTENDANCE_LATE_WEIGHT", 0.5)
    assert s.percentage == 72.2  # 6.5 / 9
    monkeypatch.setattr(settings, "ATTENDANCE_EXCUSED_POLICY", "present")
    assert s.percentage == 75.0  # 7.5 / 10
    monkeypatch.setattr(settings, "ATTENDANCE_EXCUSED_POLICY", "absent")
    assert s.percentage == 65.0  # 6.5 / 10
    assert AttendanceSummary(excused=3).percentage == 0.0  # "absent": excused counts against
    monkeypatch.setattr(settings, "ATTENDANCE_EXCUSED_POLICY", "exclude")
    assert AttendanceSummary(excused=3).percentage is None  # nothing countable was conducted
    assert summarize({}).percentage is None


def test_only_finalized_sessions_count(client, teacher_h, cls, login, hod_h):
    # Seeded student F23CSE01 is first on the roster.
    _finalized(client, teacher_h, cls, ["present", "present", "present", "present", "present"])
    s2 = start(client, teacher_h, cls["assignment"], number=2).json()["session"]
    s2 = mark(client, teacher_h, s2, ["late", "absent", "absent", "absent", "absent"]).json()
    finalize(client, teacher_h, s2)
    s3 = start(client, teacher_h, cls["assignment"], number=3).json()["session"]
    mark(client, teacher_h, s3, ["absent"] * 5)  # draft only — must not count

    student = client.get(f"{API}/dashboard/student/subjects", headers=login(STUDENT_EMAIL)).json()
    card = next(c for c in student["subjects"] if c["course_code"] == "CS-321")
    assert (card["present"], card["late"], card["absent"], card["conducted"]) == (1, 1, 0, 2)
    assert card["percentage"] == 100.0 and card["low_attendance"] is False
    assert student["policy"] == {"late_weight": 1.0, "excused_policy": "exclude", "low_threshold": 75.0}

    classes = client.get(f"{API}/attendance/classes", headers=teacher_h).json()
    cs321 = next(c for c in classes if c["course_code"] == "CS-321")
    assert cs321["finalized_sessions"] == 2 and cs321["attendance_percentage"] == 60.0  # (5 + 1) / 10
    assert client.get(f"{API}/dashboard/hod", headers=hod_h).json()["today_attendance_pct"] == 60.0


# ── Audit privacy ─────────────────────────────────────────────────────────


def test_audit_has_no_image_data_or_paths(client, teacher_h, cls, db_session):
    session = start(client, teacher_h, cls["assignment"]).json()["session"]
    upload_photo(client, teacher_h, session["id"])
    with db_session() as db:
        entries = db.scalars(select(AuditLog).where(AuditLog.action.like("attendance.%"))).all()
    dump = json.dumps([[e.old_value, e.new_value] for e in entries])
    assert "attendance/" not in dump and ".jpg" not in dump and len(dump) < 5000


def test_explicit_null_and_blank_notes(client, teacher_h, hod_h, cls):
    """Regression: an explicit null note (sent when a note is cleared) must not crash validation."""
    session = start(client, teacher_h, cls["assignment"]).json()["session"]
    rid = session["records"][0]["id"]
    s = client.patch(f"{API}/attendance/sessions/{session['id']}/records", headers=teacher_h, json={
        "version": 1, "changes": [{"record_id": rid, "status": "present", "note": "Temporary"}]}).json()
    for note in (None, "   "):
        res = client.patch(f"{API}/attendance/sessions/{session['id']}/records", headers=teacher_h, json={
            "version": s["version"], "changes": [{"record_id": rid, "note": note}]})
        assert res.status_code == 200, res.text
        s = res.json()
        assert s["records"][0]["note"] is None
    res = client.patch(f"{API}/attendance/sessions/{session['id']}", headers=teacher_h,
                       json={"version": s["version"], "note": None})
    assert res.status_code == 200
    s = client.post(f"{API}/attendance/sessions/{session['id']}/bulk", headers=teacher_h,
                    json={"version": res.json()["version"], "action": "unmarked_absent"}).json()
    final = finalize(client, teacher_h, s).json()
    res = client.post(f"{API}/attendance/records/{rid}/correct", headers=teacher_h,
                      json={"status": "excused", "note": None, "reason": "Medical certificate received"})
    assert res.status_code == 200, res.text
    assert res.json()["records"][0]["status"] == "excused" and final["status"] == "finalized"
