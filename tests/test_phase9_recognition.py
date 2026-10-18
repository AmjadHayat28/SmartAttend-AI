"""Phase 9: recognition job safety, truthful progress, friendly errors, attendance integrity,
server-side authorization and model-cache/process safety (fake engine, synthetic vectors)."""

import json
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.core.config import settings
from backend.app.face_recognition import model as face_model
from backend.app.face_recognition.classroom import ClassroomDetectConfig, detect_classroom
from backend.app.main import app
from backend.app.models import (
    AttendanceRecognitionFace,
    AttendanceRecognitionRun,
    AttendanceRecord,
    AttendanceSession,
    AttendanceSessionImage,
    Course,
    RecognitionRunStatus,
    SessionStatus,
    TeacherCourseAssignment,
)
from backend.app.services import recognition_service, storage
from backend.app.scripts.seed_demo import DEMO_PASSWORD
from tests.conftest import STUDENT_EMAIL
from tests.fake_face_engine import FakeEngine, random_identity, with_similarity
from tests.test_attendance import finalize
from tests.test_recognition import classroom_photo, rc, rec_of, run, teacher_h  # noqa: F401

API = "/api/v1"


def _records(db_session, session_id):
    with db_session() as db:
        return {r.student_id: (r.status, r.method) for r in db.scalars(
            select(AttendanceRecord).where(AttendanceRecord.session_id == session_id))}


def _session_row(db_session, session_id):
    with db_session() as db:
        s = db.get(AttendanceSession, session_id)
        return s.status, s.version


def _add_run(db_session, session_id, status=RecognitionRunStatus.PROCESSING, age_seconds=0):
    with db_session() as db:
        run_ = AttendanceRecognitionRun(
            session_id=session_id, status=status, stage="detecting" if status == RecognitionRunStatus.PROCESSING else None,
            started_at=datetime.now(UTC) - timedelta(seconds=age_seconds), model_name="fake/test-engine",
            model_version="v1", image_count=1)
        db.add(run_)
        db.commit()
        return run_.id


def _fresh(client, headers, session):
    return client.get(f"{API}/attendance/sessions/{session['id']}", headers=headers).json()


# ── A. Truthful progress ──────────────────────────────────────────────────


class _ObservingEngine(FakeEngine):
    """Records the run's committed stage/progress (read through a separate DB session) as each
    photo is analysed — what a polling page would see at that moment."""

    def __init__(self, db_session):
        super().__init__()
        self.db_session, self.seen = db_session, []
        self.on_classroom = None

    def analyze(self, image_bgr, *, purpose):
        if purpose == "classroom":
            with self.db_session() as db:
                r = db.scalar(select(AttendanceRecognitionRun).order_by(AttendanceRecognitionRun.id.desc()))
                self.seen.append((r.status.value, r.stage, r.images_processed))
            if self.on_classroom:
                self.on_classroom()
        return super().analyze(image_bgr, purpose=purpose)


@pytest.fixture()
def observing(db_session):
    engine = _ObservingEngine(db_session)
    face_model.set_engine(engine)
    return engine


def test_progress_is_committed_per_photo_and_cleared_when_done(client, teacher_h, rc, observing):
    s, v = rc["session"], rc["vec"]
    classroom_photo(client, teacher_h, s["id"], observing, 900, 600, [with_similarity(v["F23CSE01"], 0.8, 1)])
    classroom_photo(client, teacher_h, s["id"], observing, 901, 600, [random_identity(5)])
    classroom_photo(client, teacher_h, s["id"], observing, 902, 600, [])
    body = run(client, teacher_h, s).json()
    assert observing.seen == [("processing", "detecting", 0), ("processing", "detecting", 1),
                              ("processing", "detecting", 2)]
    r = body["recognition"]["run"]
    assert r["status"] == "completed_with_warnings" and r["stage"] is None and r["images_processed"] == 3


def test_page_sees_a_running_run_and_cannot_start_another(client, teacher_h, rc, fake_face_engine, db_session):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [])
    _add_run(db_session, s["id"])
    view = client.get(f"{API}/attendance/sessions/{s['id']}/recognition", headers=teacher_h).json()
    assert view["run"]["status"] == "processing" and view["run"]["stage"] == "detecting"
    assert view["can_run"] is False and view["can_decide"] is False


# ── A/E. One run at a time; nothing else changes the session meanwhile ────


def test_second_run_is_refused_while_one_is_running(client, teacher_h, rc, fake_face_engine, db_session):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [with_similarity(rc["vec"]["F23CSE01"], 0.9)])
    _add_run(db_session, s["id"])
    before = _records(db_session, s["id"])
    res = run(client, teacher_h, s)
    assert res.status_code == 409 and res.json()["detail"] == recognition_service.ALREADY_RUNNING
    assert _records(db_session, s["id"]) == before


def test_photos_finalize_and_discard_wait_for_a_running_recognition(client, teacher_h, rc, fake_face_engine,
                                                                     db_session):
    s = rc["session"]
    photo = classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [])
    s = client.post(f"{API}/attendance/sessions/{s['id']}/bulk", headers=teacher_h,
                    json={"version": photo["version"], "action": "all_absent"}).json()
    _add_run(db_session, s["id"])
    res = client.post(f"{API}/attendance/sessions/{s['id']}/images", headers=teacher_h,
                      files={"file": ("c.jpg", b"\xff\xd8", "image/jpeg")})
    assert res.status_code == 409 and "Wait for it to finish" in res.json()["detail"]
    res = client.delete(f"{API}/attendance/sessions/{s['id']}/images/{photo['images'][0]['id']}", headers=teacher_h)
    assert res.status_code == 409
    res = finalize(client, teacher_h, s)
    assert res.status_code == 409 and "before finalizing" in res.json()["detail"]
    res = client.post(f"{API}/attendance/sessions/{s['id']}/cancel", headers=teacher_h, json={"version": s["version"]})
    assert res.status_code == 409
    assert _session_row(db_session, s["id"])[0] == SessionStatus.DRAFT


def test_database_allows_only_one_processing_run_per_session(rc, db_session):
    s = rc["session"]
    _add_run(db_session, s["id"])
    with pytest.raises(IntegrityError):
        _add_run(db_session, s["id"])
    _add_run(db_session, s["id"], status=RecognitionRunStatus.FAILED)  # finished runs are unrestricted


def test_concurrent_start_race_is_refused_by_the_database(client, teacher_h, rc, fake_face_engine, db_session):
    """The pre-check sees a finished latest run, but an older run is still PROCESSING: the insert
    of a second PROCESSING run fails on the unique index → 409, attendance untouched."""
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [with_similarity(rc["vec"]["F23CSE01"], 0.9)])
    _add_run(db_session, s["id"])
    _add_run(db_session, s["id"], status=RecognitionRunStatus.COMPLETED)
    before = _records(db_session, s["id"])
    res = run(client, teacher_h, s)
    assert res.status_code == 409 and res.json()["detail"] == recognition_service.ALREADY_RUNNING
    assert _records(db_session, s["id"]) == before


def test_abandoned_run_shows_as_interrupted_and_can_be_rerun(client, teacher_h, rc, fake_face_engine, db_session):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [with_similarity(rc["vec"]["F23CSE01"], 0.9)])
    old = _add_run(db_session, s["id"], age_seconds=settings.FACE_RECOGNITION_TIMEOUT_SECONDS + 61)
    view = client.get(f"{API}/attendance/sessions/{s['id']}/recognition", headers=teacher_h).json()
    assert view["run"]["status"] == "failed" and "interrupted" in view["run"]["error_message"]
    assert view["can_run"] is True
    assert run(client, teacher_h, _fresh(client, teacher_h, s)).status_code == 200
    with db_session() as db:
        assert db.get(AttendanceRecognitionRun, old).status == RecognitionRunStatus.FAILED


# ── E. Failures never change attendance and give safe messages ─────────────


class _SlowEngine(FakeEngine):
    def analyze(self, image_bgr, *, purpose):
        if purpose == "classroom":
            time.sleep(1.1)
        return super().analyze(image_bgr, purpose=purpose)


def test_timeout_stops_between_photos_and_leaves_attendance_unchanged(client, teacher_h, rc, db_session,
                                                                       monkeypatch, audit):
    engine = _SlowEngine()
    face_model.set_engine(engine)
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], engine, 900, 600, [with_similarity(rc["vec"]["F23CSE01"], 0.9)])
    classroom_photo(client, teacher_h, s["id"], engine, 901, 600, [])
    s = _fresh(client, teacher_h, s)
    before = _records(db_session, s["id"])
    monkeypatch.setattr(settings, "FACE_RECOGNITION_TIMEOUT_SECONDS", 1)
    res = run(client, teacher_h, s)
    assert res.status_code == 503 and "took too long" in res.json()["detail"]
    assert "not changed" in res.json()["detail"]
    assert _records(db_session, s["id"]) == before and _session_row(db_session, s["id"]) == (SessionStatus.DRAFT, s["version"])
    view = client.get(f"{API}/attendance/sessions/{s['id']}/recognition", headers=teacher_h).json()
    assert view["run"]["status"] == "failed" and view["run"]["stage"] is None and view["can_run"] is True
    assert audit("recognition.run_failed")[0].new_value["error"] == "timeout"


def test_unreadable_stored_photo_gives_a_specific_message(client, teacher_h, rc, fake_face_engine, db_session,
                                                          isolated_uploads):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [])
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 901, 600, [])
    with db_session() as db:
        second = db.scalars(select(AttendanceSessionImage).order_by(AttendanceSessionImage.id)).all()[1]
        storage.resolve(second.image_path).write_bytes(b"\xff\xd8 damaged on disk")
    s = _fresh(client, teacher_h, s)
    before = _records(db_session, s["id"])
    res = run(client, teacher_h, s)
    assert res.status_code == 422 and "Classroom photo #2 could not be read" in res.json()["detail"]
    assert _records(db_session, s["id"]) == before
    view = client.get(f"{API}/attendance/sessions/{s['id']}/recognition", headers=teacher_h).json()
    assert view["run"]["status"] == "failed" and "photo #2" in view["run"]["error_message"]


def test_model_unavailable_message_is_friendly_and_details_are_logged(client, teacher_h, rc, fake_face_engine,
                                                                      monkeypatch, caplog):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [])

    def boom():
        raise face_model.FaceModelUnavailable("Model file(s) failed the integrity check: w600k_r50.onnx")

    monkeypatch.setattr(recognition_service, "get_engine", boom)
    with caplog.at_level(logging.WARNING, logger="smartclass.recognition"):
        res = run(client, teacher_h, _fresh(client, teacher_h, s))
    assert res.status_code == 503 and res.json()["detail"] == recognition_service.MODEL_UNAVAILABLE
    assert "onnx" not in res.text and "uv run" not in res.text
    assert "w600k_r50.onnx" in caplog.text  # the administrator can see why


def test_unexpected_inference_error_is_generic_for_the_teacher(client, teacher_h, rc, fake_face_engine, db_session):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [with_similarity(rc["vec"]["F23CSE01"], 0.9)])
    fake_face_engine.fail_on_classroom = True  # RuntimeError("simulated inference crash")
    res = run(client, teacher_h, _fresh(client, teacher_h, s))
    assert res.status_code == 500 and "not changed" in res.json()["detail"]
    view = client.get(f"{API}/attendance/sessions/{s['id']}/recognition", headers=teacher_h).json()
    assert "RuntimeError" not in json.dumps(view) and "simulated" not in json.dumps(view)
    assert _session_row(db_session, s["id"])[0] == SessionStatus.DRAFT  # never finalized by a failure


def test_unhandled_server_error_returns_a_safe_json_message(db_session, monkeypatch, login):
    from backend.app.database.session import get_db

    def override():
        with db_session() as session:
            yield session

    def explode(*_a, **_k):
        raise RuntimeError("secret internal detail: /srv/db password=hunter2")

    monkeypatch.setattr(recognition_service, "get_recognition", explode)
    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            token = c.post(f"{API}/auth/login", json={"email": "teacher.cse@smartclass.edu",
                                                      "password": DEMO_PASSWORD}).json()["access_token"]
            res = c.get(f"{API}/attendance/sessions/1/recognition", headers={"Authorization": f"Bearer {token}"})
    finally:
        app.dependency_overrides.clear()
    assert res.status_code == 500 and res.json() == {"detail": res.json()["detail"]}
    assert "try again" in res.json()["detail"]
    assert "secret" not in res.text and "Traceback" not in res.text and "RuntimeError" not in res.text


@pytest.mark.parametrize("case", ["missing", "other_teacher"])
def test_invalid_or_foreign_session_is_not_found(client, teacher_h, rc, login, hod_h, case):
    sid = 999_999 if case == "missing" else rc["session"]["id"]
    headers = teacher_h
    if case == "other_teacher":
        client.post(f"{API}/teachers", headers=hod_h, json={"full_name": "Other T", "email": "ot9@test.edu",
                                                         "password": "Teach@1234", "employee_id": "EMP-T-909"})
        headers = login("ot9@test.edu", "Teach@1234")
    res = client.post(f"{API}/attendance/sessions/{sid}/recognition", headers=headers, json={"version": 1})
    assert res.status_code == 404 and res.json()["detail"] == "Attendance session not found"


@pytest.mark.parametrize("what", ["assignment", "course"])
def test_inactive_class_cannot_run_recognition(client, teacher_h, rc, fake_face_engine, db_session, what):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [])
    s = _fresh(client, teacher_h, s)
    with db_session() as db:
        assignment = db.get(TeacherCourseAssignment, rc["assignment"])
        (assignment if what == "assignment" else db.get(Course, assignment.course_id)).is_active = False
        db.commit()
    res = run(client, teacher_h, s)
    assert res.status_code == 403 and "no longer assigned" in res.json()["detail"]


# ── H. Finalized attendance can never be changed by a run ──────────────────


def test_session_finalized_during_a_run_is_not_touched(client, teacher_h, rc, observing, db_session, audit):
    """Another tab finalizes while the photos are being analysed: the run must not apply (it
    would otherwise clear the earlier unconfirmed AI mark on a FINALIZED session)."""
    s, v = rc["session"], rc["vec"]
    classroom_photo(client, teacher_h, s["id"], observing, 900, 600, [with_similarity(v["F23CSE01"], 0.9)])
    first = run(client, teacher_h, _fresh(client, teacher_h, s)).json()
    assert rec_of(first["session"], "F23CSE01")["method"] == "face_recognition"  # unconfirmed AI mark
    s = client.post(f"{API}/attendance/sessions/{s['id']}/bulk", headers=teacher_h,
                    json={"version": first["session"]["version"], "action": "unmarked_absent"}).json()
    observing.add_photo(900, 600, [random_identity(42)])  # the re-run would no longer see F23CSE01

    def finalize_elsewhere():
        with db_session() as db:
            row = db.get(AttendanceSession, s["id"])
            row.status, row.finalized_at = SessionStatus.FINALIZED, datetime.now(UTC)
            db.commit()

    observing.on_classroom = finalize_elsewhere
    before = _records(db_session, s["id"])
    res = run(client, teacher_h, s)
    assert res.status_code == 409 and "finalized while recognition was running" in res.json()["detail"]
    assert _records(db_session, s["id"]) == before  # F23CSE01 still Present
    assert audit("recognition.run_failed")[0].new_value["error"] == "session_finalized"


def test_rerun_on_finalized_session_is_refused_and_changes_nothing(client, teacher_h, rc, fake_face_engine,
                                                                   db_session):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [with_similarity(rc["vec"]["F23CSE01"], 0.9)])
    body = run(client, teacher_h, _fresh(client, teacher_h, s)).json()
    s = client.post(f"{API}/attendance/sessions/{s['id']}/bulk", headers=teacher_h,
                    json={"version": body["session"]["version"], "action": "unmarked_absent"}).json()
    final = finalize(client, teacher_h, s).json()
    before = _records(db_session, s["id"])
    with db_session() as db:
        runs_before = len(db.scalars(select(AttendanceRecognitionRun)).all())
    assert run(client, teacher_h, final).status_code == 409
    assert _records(db_session, s["id"]) == before
    with db_session() as db:
        assert len(db.scalars(select(AttendanceRecognitionRun)).all()) == runs_before


# ── H. Attendance integrity ───────────────────────────────────────────────


def _assert_one_to_one(db_session, session_id):
    """Each linked face → exactly one student, each student ← at most one linked face (latest run)."""
    with db_session() as db:
        latest = db.scalar(select(AttendanceRecognitionRun).where(AttendanceRecognitionRun.session_id == session_id)
                           .order_by(AttendanceRecognitionRun.id.desc()))
        linked = [f.assigned_student_id for f in db.scalars(select(AttendanceRecognitionFace).where(
            AttendanceRecognitionFace.run_id == latest.id)) if f.decision.value in ("applied", "accepted", "assigned")]
    assert None not in linked and len(linked) == len(set(linked))


def test_no_attendance_is_ever_created_for_a_student_outside_the_roster(client, teacher_h, rc, fake_face_engine,
                                                                       db_session):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [with_similarity(rc["vec"]["OUT"], 0.99)])
    before = _records(db_session, s["id"])
    body = run(client, teacher_h, _fresh(client, teacher_h, s)).json()
    [face] = body["recognition"]["faces"]
    assert face["category"] == "no_match" and face["suggested"] is None and face["second"] is None
    assert _records(db_session, s["id"]) == before
    with db_session() as db:
        assert db.scalar(select(AttendanceRecord).where(AttendanceRecord.student_id == rc["outsider"])) is None


def test_one_student_cannot_occupy_two_faces(client, teacher_h, rc, fake_face_engine, db_session):
    s, v = rc["session"], rc["vec"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600,
                    [with_similarity(v["F23CSE01"], 0.9, 1), with_similarity(v["F23CSE01"], 0.85, 2)])
    body = run(client, teacher_h, _fresh(client, teacher_h, s)).json()
    first, second = body["recognition"]["faces"]
    assert (first["decision"], second["category"], second["decision"]) == ("applied", "duplicate", "pending")
    res = client.post(f"{API}/attendance/recognition/faces/{second['id']}/accept", headers=teacher_h,
                      json={"version": body["session"]["version"]})
    assert res.status_code == 409 and "already matched" in res.json()["detail"]
    _assert_one_to_one(db_session, s["id"])


def test_one_face_cannot_mark_two_students(client, teacher_h, rc, fake_face_engine, db_session):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [random_identity(777)])
    body = run(client, teacher_h, _fresh(client, teacher_h, s)).json()
    [face] = body["recognition"]["faces"]
    a = client.post(f"{API}/attendance/recognition/faces/{face['id']}/assign", headers=teacher_h,
                    json={"version": body["session"]["version"], "student_id": rc["sid"]["F23CSE04"]}).json()
    b = client.post(f"{API}/attendance/recognition/faces/{face['id']}/assign", headers=teacher_h,
                    json={"version": a["session"]["version"], "student_id": rc["sid"]["F23CSE05"]}).json()
    assert rec_of(b["session"], "F23CSE04")["status"] is None  # released, not left Present
    assert rec_of(b["session"], "F23CSE05")["status"] == "present"
    assert b["recognition"]["faces"][0]["assigned"]["registration_no"] == "F23CSE05"
    _assert_one_to_one(db_session, s["id"])


@pytest.mark.parametrize("manual", ["absent", "present", "late", "excused"])
def test_manual_mark_is_never_overwritten_by_a_confident_match(client, teacher_h, rc, fake_face_engine, manual):
    s = rc["session"]
    s = client.patch(f"{API}/attendance/sessions/{s['id']}/records", headers=teacher_h, json={
        "version": s["version"], "changes": [{"record_id": rec_of(s, "F23CSE01")["id"], "status": manual}]}).json()
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [with_similarity(rc["vec"]["F23CSE01"], 0.97)])
    body = run(client, teacher_h, _fresh(client, teacher_h, s)).json()
    r = rec_of(body["session"], "F23CSE01")
    assert (r["status"], r["method"]) == (manual, "manual")
    assert body["recognition"]["faces"][0]["decision"] == "manual_kept"


def test_failed_run_never_finalizes_or_changes_records(client, teacher_h, rc, fake_face_engine, db_session):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [with_similarity(rc["vec"]["F23CSE01"], 0.9)])
    s = _fresh(client, teacher_h, s)
    before = _records(db_session, s["id"])
    fake_face_engine.fail_on_classroom = True
    assert run(client, teacher_h, s).status_code == 500
    assert _session_row(db_session, s["id"]) == (SessionStatus.DRAFT, s["version"])
    assert _records(db_session, s["id"]) == before


def test_accepting_a_low_confidence_suggestion_changes_only_that_student(client, teacher_h, rc, fake_face_engine,
                                                                        db_session):
    s, v = rc["session"], rc["vec"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600,
                    [with_similarity(v["F23CSE05"], 0.42), random_identity(9)])
    body = run(client, teacher_h, _fresh(client, teacher_h, s)).json()
    low = body["recognition"]["faces"][0]
    assert low["category"] == "low_confidence" and low["decision"] == "pending"
    before = _records(db_session, s["id"])
    client.post(f"{API}/attendance/recognition/faces/{low['id']}/accept", headers=teacher_h,
                json={"version": body["session"]["version"]})
    after = _records(db_session, s["id"])
    changed = {sid_ for sid_ in after if after[sid_] != before[sid_]}
    assert changed == {rc["sid"]["F23CSE05"]}
    assert after[rc["sid"]["F23CSE05"]][0].value == "present"


def test_unknown_and_covered_faces_stay_unknown_until_the_teacher_acts(client, teacher_h, rc, fake_face_engine,
                                                                      db_session):
    """A masked/covered face yields an embedding unlike anyone enrolled: it stays unknown through
    re-runs and only the teacher's explicit assignment changes attendance."""
    s, v = rc["session"], rc["vec"]
    covered = with_similarity(v["F23CSE04"], 0.2, 3)  # below the low threshold
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [covered, random_identity(31)])
    before = _records(db_session, s["id"])
    body = run(client, teacher_h, _fresh(client, teacher_h, s)).json()
    assert [(f["category"], f["decision"]) for f in body["recognition"]["faces"]] == [("no_match", "none")] * 2
    again = run(client, teacher_h, body["session"]).json()
    assert [(f["category"], f["decision"]) for f in again["recognition"]["faces"]] == [("no_match", "none")] * 2
    assert _records(db_session, s["id"]) == before
    face = again["recognition"]["faces"][0]
    done = client.post(f"{API}/attendance/recognition/faces/{face['id']}/assign", headers=teacher_h,
                       json={"version": again["session"]["version"], "student_id": rc["sid"]["F23CSE04"]}).json()
    assert rec_of(done["session"], "F23CSE04")["method"] == "face_recognition_confirmed"


# ── G. Server-side authorization for every recognition endpoint ───────────


def test_recognition_endpoints_authorization_matrix(client, teacher_h, rc, fake_face_engine, hod_h, admin_h, login):
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600,
                    [with_similarity(rc["vec"]["F23CSE05"], 0.42)])
    body = run(client, teacher_h, _fresh(client, teacher_h, s)).json()
    face_id, version = body["recognition"]["faces"][0]["id"], body["session"]["version"]
    client.post(f"{API}/teachers", headers=hod_h, json={"full_name": "Other T", "email": "ot8@test.edu",
                                                     "password": "Teach@1234", "employee_id": "EMP-T-808"})
    callers = {"other_teacher": login("ot8@test.edu", "Teach@1234"), "hod": hod_h, "super_admin": admin_h,
               "student": login(STUDENT_EMAIL), "anonymous": {}}
    expected = {"other_teacher": 404, "hod": 403, "super_admin": 403, "student": 403, "anonymous": 401}
    endpoints = [
        ("post", f"/attendance/sessions/{s['id']}/recognition", {"version": version}),
        ("get", f"/attendance/sessions/{s['id']}/recognition", None),
        ("post", f"/attendance/recognition/faces/{face_id}/accept", {"version": version}),
        ("post", f"/attendance/recognition/faces/{face_id}/assign", {"version": version, "student_id": rc["sid"]["F23CSE05"]}),
        ("post", f"/attendance/recognition/faces/{face_id}/reject", {"version": version}),
        ("post", f"/attendance/sessions/{s['id']}/images", None),
        ("get", f"/attendance/images/{body['session']['images'][0]['id']}", None),
    ]
    for who, headers in callers.items():
        for method, path, payload in endpoints:
            kwargs = {"headers": headers}
            if payload is not None:
                kwargs["json"] = payload
            elif path.endswith("/images"):
                kwargs["files"] = {"file": ("c.jpg", b"\xff\xd8", "image/jpeg")}
            res = getattr(client, method)(f"{API}{path}", **kwargs)
            assert res.status_code == expected[who], (who, method, path, res.status_code, res.text)
    # Nothing above changed the session; the assigned teacher still can act.
    ok = client.post(f"{API}/attendance/recognition/faces/{face_id}/accept", headers=teacher_h,
                     json={"version": version})
    assert ok.status_code == 200


# ── D. Model cache / process safety ───────────────────────────────────────


class _Engine:
    def __init__(self, name):
        self.model_name = f"insightface/{name}"
        self.model_version, self.dimension, self.detector_name = "test", 512, "SCRFD test"
        self.fallback_from = None


@pytest.fixture()
def no_engine(monkeypatch):
    monkeypatch.setattr(settings, "FACE_RECOGNITION_MODEL", "buffalo_l")
    monkeypatch.setattr(settings, "FACE_RECOGNITION_FALLBACK_MODEL", "buffalo_sc")
    face_model.set_engine(None)
    yield
    face_model.set_engine(None)


def test_concurrent_first_requests_load_the_model_exactly_once(monkeypatch, no_engine):
    calls = []

    def slow_load(name):
        calls.append(name)
        time.sleep(0.3)
        return _Engine(name)

    monkeypatch.setattr(face_model, "_load", slow_load)
    results, barrier = [], threading.Barrier(8)

    def worker():
        barrier.wait()
        results.append(face_model.get_engine())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls == ["buffalo_l"] and len(results) == 8 and all(r is results[0] for r in results)


def test_fallback_is_loaded_once_logged_and_reused(monkeypatch, no_engine, caplog):
    calls = []

    def load(name):
        calls.append(name)
        if name == "buffalo_l":
            raise face_model.FaceModelUnavailable("Model file(s) failed the integrity check: det_10g.onnx")
        return _Engine(name)

    monkeypatch.setattr(face_model, "_load", load)
    with caplog.at_level(logging.INFO, logger="smartclass.recognition"):
        engines = [face_model.get_engine() for _ in range(4)]
    assert calls == ["buffalo_l", "buffalo_sc"]  # never reloaded
    assert all(e is engines[0] for e in engines) and engines[0].fallback_from == "buffalo_l"
    assert "det_10g.onnx" in caplog.text and "FALLBACK" in caplog.text


def test_failed_load_is_not_retried_on_every_request(monkeypatch, no_engine, caplog):
    calls = []
    clock = [1000.0]

    def load(name):
        calls.append(name)
        raise face_model.FaceModelUnavailable(f"Face recognition model '{name}' is not installed.")

    monkeypatch.setattr(face_model, "_load", load)
    monkeypatch.setattr(face_model.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(settings, "FACE_RECOGNITION_RETRY_SECONDS", 60)
    with caplog.at_level(logging.ERROR, logger="smartclass.recognition"):
        for _ in range(3):
            with pytest.raises(face_model.FaceModelUnavailable):
                face_model.get_engine()
    assert calls == ["buffalo_l", "buffalo_sc"]  # one attempt (primary + fallback), then refused fast
    assert "UNAVAILABLE" in caplog.text and "'buffalo_sc'" in caplog.text
    clock[0] += 61
    with pytest.raises(face_model.FaceModelUnavailable):
        face_model.get_engine()
    assert calls == ["buffalo_l", "buffalo_sc"] * 2  # retried after the cool-down


def test_preload_never_raises(monkeypatch, no_engine):
    def load(name):
        raise face_model.FaceModelUnavailable("not installed")

    monkeypatch.setattr(face_model, "_load", load)
    face_model.preload_engine()  # logged, not raised


def test_startup_preloads_the_model_in_the_background(monkeypatch):
    started = threading.Event()
    monkeypatch.setattr(settings, "FACE_RECOGNITION_PRELOAD", True)
    monkeypatch.setattr(face_model, "preload_engine", lambda: started.set())
    with TestClient(app):
        assert started.wait(5)
    started.clear()
    monkeypatch.setattr(settings, "FACE_RECOGNITION_PRELOAD", False)
    with TestClient(app):
        assert not started.wait(0.3)


# ── C. Identical detector passes run once, with identical results ─────────


class _FakeSCRFD:
    """Mimics SCRFD.detect(): per-size candidates, then one merge (here: concatenation)."""

    def __init__(self):
        self.inner_calls = []

    def _detect_candidates(self, img, input_size, threshold):
        self.inner_calls.append(tuple(input_size))
        s = input_size[0] / 1000
        boxes = np.array([[100 * s, 100, 160 * s, 170, 0.92], [400, 300 * s, 470, 380 * s, 0.88]], np.float32)
        kps = np.repeat(boxes[:, None, :2], 5, axis=1)
        return boxes, kps

    def detect(self, img, input_size=None, max_num=0, det_thresh=None):
        outs = [self._detect_candidates(img, size, det_thresh) for size in input_size]
        return np.vstack([b for b, _ in outs]), np.vstack([k for _, k in outs])


def _engine_with(det):
    engine = object.__new__(face_model.InsightFaceEngine)
    engine._app = SimpleNamespace(det_model=det)
    return engine


def test_upright_640_pass_is_reused_and_results_are_identical():
    img = np.zeros((1000, 1200, 3), np.uint8)
    cfg = ClassroomDetectConfig(sizes=((640, 640), (1024, 1024)), tiling=False)
    plain_det = _FakeSCRFD()
    plain = detect_classroom(_engine_with(plain_det)._detect, img, cfg)
    det = _FakeSCRFD()
    engine = _engine_with(det)
    with engine._reuse_identical_passes():
        memo = detect_classroom(engine._detect, img, cfg)
    assert plain_det.inner_calls == [(640, 640), (640, 640), (1024, 1024)]
    assert det.inner_calls == [(640, 640), (1024, 1024)]  # the repeat was skipped
    assert np.array_equal(plain.boxes, memo.boxes) and np.array_equal(plain.kps, memo.kps)
    assert "_detect_candidates" not in vars(det)  # restored after the photo
    assert set(memo.stage_ms) == {"orient", "full", "tiles"}


def test_memo_never_confuses_different_arrays():
    det = _FakeSCRFD()
    engine = _engine_with(det)
    a, b = np.zeros((50, 50, 3), np.uint8), np.zeros((50, 50, 3), np.uint8)
    with engine._reuse_identical_passes():
        det.detect(a, [(640, 640)], det_thresh=0.5)
        det.detect(b, [(640, 640)], det_thresh=0.5)  # equal pixels, different array → computed again
        det.detect(a, [(640, 640)], det_thresh=0.5)
    assert det.inner_calls == [(640, 640), (640, 640)]


def test_memo_is_skipped_when_the_detector_has_no_candidate_step():
    det = SimpleNamespace(detect=lambda img, input_size, max_num, det_thresh: (np.zeros((0, 5)), None))
    engine = _engine_with(det)
    with engine._reuse_identical_passes():
        assert engine._detect(np.zeros((10, 10, 3), np.uint8), [(640, 640)])[0].shape == (0, 5)
