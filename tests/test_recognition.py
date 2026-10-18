"""Phase 6: face recognition pre-fills DRAFT attendance (synthetic vectors only, fake engine)."""

import json

import cv2
import numpy as np
import pytest
from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.face_recognition import model as face_model
from backend.app.models import (
    AttendanceRecognitionRun,
    AuditLog,
    FaceEmbedding,
    FaceEnrollmentStatus,
    FaceImageType,
    Student,
    StudentFaceImage,
    TeacherCourseAssignment,
)
from tests import imaging
from tests.conftest import STUDENT_EMAIL, TEACHER_EMAIL
from tests.fake_face_engine import blend, random_identity, with_similarity
from tests.test_attendance import TODAY, finalize, mark, start, upload_photo

API = "/api/v1"


def give_profile(db_session, engine, student_id: int, identity: np.ndarray, poses=3) -> None:
    """Approved face enrollment + fresh synthetic embeddings (one per pose photo)."""
    with db_session() as db:
        student = db.get(Student, student_id)
        student.face_enrollment_status = FaceEnrollmentStatus.APPROVED
        for i, pose in enumerate([FaceImageType.FRONT, FaceImageType.LEFT, FaceImageType.RIGHT][:poses]):
            image = StudentFaceImage(student_id=student_id, image_path=f"faces/{student_id}/{'%032x' % (i + 1)}.jpg",
                                     image_type=pose, width=640, height=640, file_size=1)
            db.add(image)
            db.flush()
            db.refresh(image)
            # The front photo's embedding *is* the identity, so a classroom face built with
            # similarity s to the identity scores exactly s; other poses vary around it.
            vec = identity if i == 0 else with_similarity(identity, 0.92, seed=student_id * 10 + i)
            db.add(FaceEmbedding(student_id=student_id, face_image_id=image.id, embedding_vector=vec.tobytes(),
                                 dimension=vec.shape[0], model_name=engine.model_name,
                                 model_version=engine.model_version, source_updated_at=image.updated_at))
        db.commit()


def classroom_photo(client, headers, session_id, engine, width, height, embeddings):
    """Upload a synthetic classroom photo of an exact size and tell the fake engine its faces."""
    engine.add_photo(width, height, embeddings)
    img = cv2.resize(imaging.no_face(), (width, height))
    res = client.post(f"{API}/attendance/sessions/{session_id}/images", headers=headers,
                      files={"file": ("c.jpg", imaging.jpeg(img), "image/jpeg")})
    assert res.status_code == 201, res.text
    return res.json()


def run(client, headers, session):
    return client.post(f"{API}/attendance/sessions/{session['id']}/recognition", headers=headers,
                       json={"version": session["version"]})


def rec_of(session, reg_no):
    return next(r for r in session["records"] if r["registration_no"] == reg_no)


@pytest.fixture()
def teacher_h(login):
    return login(TEACHER_EMAIL)


@pytest.fixture()
def rc(client, hod_h, ids, db_session, fake_face_engine, teacher_h):
    """CS-321/A roster of 5: F23CSE01/04/05 have profiles; F23CSE06 has none; F23CSE03 is pending.
    Also an approved *outsider* (section B, not on the roster) with a profile."""
    for i in range(4, 7):
        client.post(f"{API}/students", headers=hod_h, json={
            "full_name": f"Student {i}", "email": f"s{i}@test.edu", "password": "Student@123",
            "registration_no": f"F23CSE0{i}", "batch_id": ids["batch"], "semester_id": ids["semester"],
            "section_id": ids["section_a"]})
    outsider = client.post(f"{API}/students", headers=hod_h, json={
        "full_name": "Out Sider", "email": "out@test.edu", "password": "Student@123", "registration_no": "F23CSE99",
        "batch_id": ids["batch"], "semester_id": ids["semester"], "section_id": ids["section_b"]}).json()
    with db_session() as db:
        sid = {s.registration_no: s.id for s in db.scalars(select(Student))}
        assignment = db.scalar(select(TeacherCourseAssignment.id).where(
            TeacherCourseAssignment.course_id == ids["courses"]["CS-321"],
            TeacherCourseAssignment.section_id == ids["section_a"]))
    assert client.post(f"{API}/enrollments/bulk", headers=teacher_h,
                       json={"assignment_id": assignment}).status_code == 200
    vec = {"F23CSE01": random_identity(101), "F23CSE04": random_identity(104), "F23CSE05": random_identity(105),
           "OUT": random_identity(199)}
    for reg in ("F23CSE01", "F23CSE04", "F23CSE05"):
        give_profile(db_session, fake_face_engine, sid[reg], vec[reg])
    give_profile(db_session, fake_face_engine, outsider["id"], vec["OUT"])
    session = start(client, teacher_h, assignment).json()["session"]
    return {"session": session, "vec": vec, "sid": sid, "outsider": outsider["id"], "assignment": assignment}


# ── Core flow ─────────────────────────────────────────────────────────────


def test_confident_matches_prefill_present_only(client, teacher_h, rc, fake_face_engine, audit):
    s = rc["session"]
    v = rc["vec"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600,
                    [with_similarity(v["F23CSE01"], 0.8, 1), with_similarity(v["F23CSE04"], 0.75, 2),
                     random_identity(555)])
    res = run(client, teacher_h, s)
    assert res.status_code == 200, res.text
    body = res.json()
    r, session = body["recognition"]["run"], body["session"]
    assert r["status"] == "completed_with_warnings"  # two roster students cannot be recognised
    assert (r["faces_detected"], r["confident_count"], r["unknown_count"], r["applied_count"]) == (3, 2, 1, 2)
    assert (r["roster_size"], r["eligible_count"], r["students_recognized"]) == (5, 3, 2)
    assert {m["registration_no"] for m in r["missing_students"]} == {"F23CSE03", "F23CSE06"}
    assert r["thresholds"] == {"confident": 0.5, "low": 0.35, "margin": 0.06}

    a = rec_of(session, "F23CSE01")
    assert (a["status"], a["method"]) == ("present", "face_recognition") and a["confidence"] == pytest.approx(0.8, abs=1e-3)
    assert rec_of(session, "F23CSE05")["status"] is None  # not seen → unchanged, NOT absent
    assert rec_of(session, "F23CSE06")["status"] is None
    assert session["status"] == "draft"  # AI never finalizes
    faces = body["recognition"]["faces"]
    assert [f["decision"] for f in faces] == ["applied", "applied", "none"]
    assert faces[0]["bbox"] == {"x": 20, "y": 40, "width": 60, "height": 60} and faces[0]["image_width"] == 900
    assert audit("recognition.run_started") and audit("recognition.run_completed") and audit("recognition.matches_applied")


def test_low_confidence_needs_teacher_acceptance(client, teacher_h, rc, fake_face_engine, audit):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [with_similarity(rc["vec"]["F23CSE05"], 0.42)])
    body = run(client, teacher_h, s).json()
    [face] = body["recognition"]["faces"]
    assert face["category"] == "low_confidence" and face["decision"] == "pending"
    assert face["suggested"]["registration_no"] == "F23CSE05"
    assert rec_of(body["session"], "F23CSE05")["status"] is None  # not marked until accepted
    res = client.post(f"{API}/attendance/recognition/faces/{face['id']}/accept", headers=teacher_h,
                      json={"version": body["session"]["version"]})
    assert res.status_code == 200
    r = rec_of(res.json()["session"], "F23CSE05")
    assert (r["status"], r["method"]) == ("present", "face_recognition_confirmed")
    assert res.json()["recognition"]["faces"][0]["decision"] == "accepted"
    assert audit("recognition.suggestion_accepted")


def test_ambiguous_and_duplicate_results(client, teacher_h, rc, fake_face_engine):
    s, v = rc["session"], rc["vec"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [
        blend([(v["F23CSE04"], 0.62), (v["F23CSE05"], 0.59)]),  # ambiguous between 04 and 05
        with_similarity(v["F23CSE01"], 0.9, 1),
        with_similarity(v["F23CSE01"], 0.7, 2),  # duplicate of 01 in the same photo
    ])
    body = run(client, teacher_h, s).json()
    cats = [(f["category"], f["decision"]) for f in body["recognition"]["faces"]]
    assert cats == [("ambiguous", "pending"), ("confident", "applied"), ("duplicate", "pending")]
    assert rec_of(body["session"], "F23CSE04")["status"] is None and rec_of(body["session"], "F23CSE05")["status"] is None
    assert body["recognition"]["run"]["ambiguous_count"] == 1 and body["recognition"]["run"]["duplicate_count"] == 1


def test_same_student_in_two_photos_counted_once(client, teacher_h, rc, fake_face_engine):
    s, v = rc["session"], rc["vec"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [with_similarity(v["F23CSE01"], 0.7, 1)])
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 901, 600, [with_similarity(v["F23CSE01"], 0.9, 2)])
    body = run(client, teacher_h, s).json()
    faces = body["recognition"]["faces"]
    assert [(f["is_primary"], f["decision"]) for f in faces] == [(False, "none"), (True, "applied")]
    assert body["recognition"]["run"]["students_recognized"] == 1 and body["recognition"]["run"]["applied_count"] == 1
    assert rec_of(body["session"], "F23CSE01")["confidence"] == pytest.approx(0.9, abs=1e-3)


def test_recognition_is_scoped_to_the_session_roster(client, teacher_h, rc, fake_face_engine):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [with_similarity(rc["vec"]["OUT"], 0.99)])
    body = run(client, teacher_h, s).json()
    [face] = body["recognition"]["faces"]
    assert face["category"] == "no_match" and face["suggested"] is None  # the outsider is never a candidate
    res = client.post(f"{API}/attendance/recognition/faces/{face['id']}/assign", headers=teacher_h,
                      json={"version": body["session"]["version"], "student_id": rc["outsider"]})
    assert res.status_code == 422 and "roster" in res.json()["detail"]


# ── Teacher decisions ─────────────────────────────────────────────────────


def test_assign_unknown_face_and_one_to_one_protection(client, teacher_h, rc, fake_face_engine, audit):
    s, v = rc["session"], rc["vec"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600,
                    [with_similarity(v["F23CSE01"], 0.85), random_identity(777)])
    body = run(client, teacher_h, s).json()
    known, unknown = body["recognition"]["faces"]
    version = body["session"]["version"]
    res = client.post(f"{API}/attendance/recognition/faces/{unknown['id']}/assign", headers=teacher_h,
                      json={"version": version, "student_id": rc["sid"]["F23CSE06"]})
    assert res.status_code == 200
    assert rec_of(res.json()["session"], "F23CSE06")["method"] == "face_recognition_confirmed"
    version = res.json()["session"]["version"]
    # F23CSE01 is already matched to the other face: refused unless the teacher confirms the move.
    clash = client.post(f"{API}/attendance/recognition/faces/{unknown['id']}/assign", headers=teacher_h,
                        json={"version": version, "student_id": rc["sid"]["F23CSE01"]})
    assert clash.status_code == 409
    moved = client.post(f"{API}/attendance/recognition/faces/{unknown['id']}/assign", headers=teacher_h,
                        json={"version": version, "student_id": rc["sid"]["F23CSE01"], "replace": True}).json()
    faces = {f["id"]: f for f in moved["recognition"]["faces"]}
    assert faces[known["id"]]["decision"] == "rejected" and faces[unknown["id"]]["assigned"]["registration_no"] == "F23CSE01"
    assert rec_of(moved["session"], "F23CSE06")["status"] is None  # the face's previous student is released
    assert rec_of(moved["session"], "F23CSE01")["status"] == "present"
    assert audit("recognition.face_assigned")


def test_reject_confident_match_reverts_ai_mark(client, teacher_h, rc, fake_face_engine, audit):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [with_similarity(rc["vec"]["F23CSE04"], 0.8)])
    body = run(client, teacher_h, s).json()
    [face] = body["recognition"]["faces"]
    res = client.post(f"{API}/attendance/recognition/faces/{face['id']}/reject", headers=teacher_h,
                      json={"version": body["session"]["version"]})
    assert rec_of(res.json()["session"], "F23CSE04")["status"] is None
    assert res.json()["recognition"]["faces"][0]["decision"] == "rejected"
    assert audit("recognition.suggestion_rejected")


# ── Manual decisions and re-runs ──────────────────────────────────────────


def test_manual_decisions_are_preserved(client, teacher_h, rc, fake_face_engine, audit):
    s, v = rc["session"], rc["vec"]
    absent = rec_of(s, "F23CSE01")
    s = client.patch(f"{API}/attendance/sessions/{s['id']}/records", headers=teacher_h, json={
        "version": s["version"], "changes": [{"record_id": absent["id"], "status": "absent"}]}).json()
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600,
                    [with_similarity(v["F23CSE01"], 0.9), with_similarity(v["F23CSE04"], 0.8)])
    body = run(client, teacher_h, s).json()
    faces = body["recognition"]["faces"]
    assert faces[0]["decision"] == "manual_kept" and body["recognition"]["run"]["preserved_count"] == 1
    assert rec_of(body["session"], "F23CSE01")["status"] == "absent"  # teacher's decision stands

    # The teacher overrides an AI mark; a re-run keeps the teacher's value.
    ai = rec_of(body["session"], "F23CSE04")
    s = client.patch(f"{API}/attendance/sessions/{s['id']}/records", headers=teacher_h, json={
        "version": body["session"]["version"], "changes": [{"record_id": ai["id"], "status": "late"}]}).json()
    assert rec_of(s, "F23CSE04")["method"] == "manual"
    assert audit("recognition.ai_overridden")[0].new_value == {"student_ids": [rc["sid"]["F23CSE04"]]}
    again = run(client, teacher_h, s).json()
    assert rec_of(again["session"], "F23CSE04")["status"] == "late"
    assert rec_of(again["session"], "F23CSE01")["status"] == "absent"


def test_rerun_recomputes_unconfirmed_ai_marks_but_keeps_confirmed(client, teacher_h, rc, fake_face_engine, db_session):
    s, v = rc["session"], rc["vec"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600,
                    [with_similarity(v["F23CSE04"], 0.8), with_similarity(v["F23CSE05"], 0.42)])
    body = run(client, teacher_h, s).json()
    low = body["recognition"]["faces"][1]
    body = client.post(f"{API}/attendance/recognition/faces/{low['id']}/accept", headers=teacher_h,
                       json={"version": body["session"]["version"]}).json()
    old_face = low["id"]
    # The photo is re-analysed and F23CSE04 is no longer found.
    fake_face_engine.add_photo(900, 600, [with_similarity(v["F23CSE05"], 0.42)])
    rerun = run(client, teacher_h, body["session"]).json()
    assert rec_of(rerun["session"], "F23CSE04")["status"] is None  # stale AI mark cleared, NOT absent
    assert rec_of(rerun["session"], "F23CSE05")["method"] == "face_recognition_confirmed"  # teacher-confirmed kept
    with db_session() as db:
        assert len(db.scalars(select(AttendanceRecognitionRun)).all()) == 2
    stale = client.post(f"{API}/attendance/recognition/faces/{old_face}/reject", headers=teacher_h,
                        json={"version": rerun["session"]["version"]})
    assert stale.status_code == 409 and "newer recognition run" in stale.json()["detail"]
    # Records are never duplicated by re-runs.
    assert len(rerun["session"]["records"]) == 5


def test_finalize_after_recognition_is_still_manual(client, teacher_h, rc, fake_face_engine):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [with_similarity(rc["vec"]["F23CSE01"], 0.8)])
    body = run(client, teacher_h, s).json()
    assert finalize(client, teacher_h, body["session"]).status_code == 422  # others still unmarked
    s = client.post(f"{API}/attendance/sessions/{s['id']}/bulk", headers=teacher_h,
                    json={"version": body["session"]["version"], "action": "unmarked_absent"}).json()
    final = finalize(client, teacher_h, s).json()
    assert final["status"] == "finalized" and rec_of(final, "F23CSE01")["method"] == "face_recognition"
    assert run(client, teacher_h, final).status_code == 409  # no recognition on finalized sessions


# ── Preconditions and access ──────────────────────────────────────────────


def test_preconditions(client, teacher_h, rc, fake_face_engine):
    s = rc["session"]
    res = run(client, teacher_h, s)
    assert res.status_code == 422 and "classroom photo" in res.json()["detail"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [])
    stale = client.post(f"{API}/attendance/sessions/{s['id']}/recognition", headers=teacher_h, json={"version": 0})
    assert stale.status_code == 409


def test_no_eligible_profiles_message(client, teacher_h, cls_without_profiles, fake_face_engine):
    s = cls_without_profiles
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [random_identity(1)])
    res = run(client, teacher_h, s)
    assert res.status_code == 422
    assert res.json()["detail"] == "No students in this class have approved face recognition profiles yet."


@pytest.fixture()
def cls_without_profiles(client, teacher_h, ids, db_session):
    with db_session() as db:
        assignment = db.scalar(select(TeacherCourseAssignment.id).where(
            TeacherCourseAssignment.course_id == ids["courses"]["CS-321"]))
    return start(client, teacher_h, assignment).json()["session"]


def test_access_control(client, rc, hod_h, admin_h, login, fake_face_engine, teacher_h):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [with_similarity(rc["vec"]["F23CSE01"], 0.8)])
    assert client.post(f"{API}/attendance/sessions/{s['id']}/recognition", headers=hod_h,
                       json={"version": s["version"]}).status_code == 403  # teachers only
    run(client, teacher_h, client.get(f"{API}/attendance/sessions/{s['id']}", headers=teacher_h).json())
    assert client.get(f"{API}/attendance/sessions/{s['id']}/recognition", headers=teacher_h).status_code == 200
    assert client.get(f"{API}/attendance/sessions/{s['id']}/recognition", headers=hod_h).status_code == 403
    assert client.get(f"{API}/attendance/sessions/{s['id']}/recognition", headers=admin_h).status_code == 403
    assert client.get(f"{API}/attendance/sessions/{s['id']}/recognition", headers=login(STUDENT_EMAIL)).status_code == 403
    # Another department's HOD sees nothing.
    client.post(f"{API}/hods", headers=admin_h, json={"full_name": "EE Head", "email": "hod.ee2@test.edu",
                "password": "HodPass@123", "employee_id": "EMP-HOD-EE2",
                "department_id": client.get(f"{API}/departments", headers=admin_h).json()[1]["id"]})
    ee_hod = login("hod.ee2@test.edu", "HodPass@123")
    assert client.get(f"{API}/attendance/sessions/{s['id']}/recognition", headers=ee_hod).status_code == 403


def test_other_teacher_cannot_run(client, rc, hod_h, login, fake_face_engine, teacher_h):
    client.post(f"{API}/teachers", headers=hod_h, json={"full_name": "Other T", "email": "ot@test.edu",
                                                     "password": "Teach@1234", "employee_id": "EMP-T-888"})
    other = login("ot@test.edu", "Teach@1234")
    s = rc["session"]
    assert client.post(f"{API}/attendance/sessions/{s['id']}/recognition", headers=other,
                       json={"version": s["version"]}).status_code == 404


# ── Failure safety, model availability, privacy ───────────────────────────


def test_failure_leaves_attendance_untouched(client, teacher_h, rc, fake_face_engine, audit):
    s = rc["session"]
    s = client.patch(f"{API}/attendance/sessions/{s['id']}/records", headers=teacher_h, json={
        "version": s["version"], "changes": [{"record_id": rec_of(s, "F23CSE04")["id"], "status": "late"}]}).json()
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [with_similarity(rc["vec"]["F23CSE01"], 0.9)])
    fake_face_engine.fail_on_classroom = True
    res = run(client, teacher_h, s)
    assert res.status_code == 500 and "not changed" in res.json()["detail"]
    after = client.get(f"{API}/attendance/sessions/{s['id']}", headers=teacher_h).json()
    assert [r["status"] for r in after["records"]] == [r["status"] for r in s["records"]]
    assert after["version"] == s["version"]
    rec = client.get(f"{API}/attendance/sessions/{s['id']}/recognition", headers=teacher_h).json()
    assert rec["run"]["status"] == "failed" and "not changed" in rec["run"]["error_message"]
    assert audit("recognition.run_failed")
    fake_face_engine.fail_on_classroom = False
    assert run(client, teacher_h, after).status_code == 200  # can simply be retried


def test_model_unavailable_and_disabled(client, teacher_h, rc, fake_face_engine, monkeypatch):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [])

    def boom():
        raise face_model.FaceModelUnavailable("Face recognition model 'buffalo_l' is not installed.")

    monkeypatch.setattr("backend.app.services.recognition_service.get_engine", boom)
    res = run(client, teacher_h, s)
    assert res.status_code == 503 and "not installed" in res.json()["detail"]
    monkeypatch.setattr(settings, "FACE_RECOGNITION_ENABLED", False)
    assert run(client, teacher_h, s).status_code == 503


def test_embeddings_never_exposed(client, teacher_h, hod_h, rc, fake_face_engine, db_session):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [with_similarity(rc["vec"]["F23CSE01"], 0.8)])
    bodies = [run(client, teacher_h, s).json(),
              client.get(f"{API}/attendance/sessions/{s['id']}/recognition", headers=hod_h).json(),
              client.get(f"{API}/attendance/sessions/{s['id']}", headers=hod_h).json()]
    dump = json.dumps(bodies).lower()
    assert "embedding" not in dump and "vector" not in dump
    with db_session() as db:
        audit_dump = json.dumps([[a.old_value, a.new_value] for a in db.scalars(select(AuditLog))])
        one_vector = db.scalar(select(FaceEmbedding.embedding_vector))
    assert len(audit_dump) < 20000 and one_vector.hex()[:32] not in audit_dump
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if "embedding" in p.lower()]
