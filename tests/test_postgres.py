"""Phase 10: PostgreSQL-only checks — migrations, schema features, real concurrency and timezones.

Skipped unless the suite runs on PostgreSQL:
    $env:SMARTCLASS_TEST_DATABASE_URL = "postgresql+psycopg2://USER:PASSWORD@localhost:5432/smartclass_phase10_test"
    uv run pytest -m postgres

Concurrency tests use real threads, a real connection pool and real PostgreSQL transactions
and row locks — SQLite's single-writer behaviour is not taken as proof of anything here.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError

from backend.app.database.init_db import alembic_config
from backend.app.face_recognition import model as face_model
from backend.app.models import (
    AttendanceRecognitionRun,
    AttendanceRecord,
    AttendanceSession,
    RecognitionRunStatus,
    SessionStatus,
    StudentCourseEnrollment,
    TeacherCourseAssignment,
)
from backend.app.services import attendance_service
from tests.conftest import ON_POSTGRES, TEST_DATABASE_URL
from tests.fake_face_engine import FakeEngine, random_identity, with_similarity
from tests.test_attendance import TODAY, finalize
from tests.test_recognition import classroom_photo, rc, rec_of, run, teacher_h  # noqa: F401

pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not ON_POSTGRES, reason="set SMARTCLASS_TEST_DATABASE_URL to a PostgreSQL test DB")]

API = "/api/v1"


def parallel(*calls):
    """Run the callables at the same moment in separate threads; return their results in order."""
    start = threading.Barrier(len(calls))

    def go(fn):
        start.wait()
        return fn()

    with ThreadPoolExecutor(len(calls)) as pool:
        return [f.result(timeout=120) for f in [pool.submit(go, c) for c in calls]]


# ── Migrations 0001 → head on an empty PostgreSQL database ────────────────


@pytest.fixture()
def empty_db():
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    yield engine
    engine.dispose()


def test_all_migrations_apply_to_an_empty_database_and_match_the_models(empty_db):
    cfg = alembic_config(TEST_DATABASE_URL)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    head = ScriptDirectory.from_config(cfg).get_current_head()
    with empty_db.connect() as conn:
        assert MigrationContext.configure(conn).get_current_revision() == head == "0008"
    command.check(cfg)  # raises if models and migrations disagree on PostgreSQL
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    with empty_db.connect() as conn:
        assert MigrationContext.configure(conn).get_current_revision() == "0008"


def test_postgres_schema_features(empty_db):
    cfg = alembic_config(TEST_DATABASE_URL)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    with empty_db.connect() as conn:
        indexes = dict(conn.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")).all())
        assert "WHERE" in indexes["uq_recognition_runs_one_processing"]
        assert "UNIQUE" in indexes["uq_attendance_sessions_active_slot"] and "cancelled" in indexes[
            "uq_attendance_sessions_active_slot"]
        types = dict(conn.execute(text(
            "SELECT table_name || '.' || column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public'")).all())
        assert types["attendance_recognition_runs.diagnostics"] == "jsonb"
        assert types["audit_logs.new_value"] == "jsonb"
        assert types["attendance_sessions.finalized_at"] == "timestamp with time zone"
        assert types["face_embeddings.embedding_vector"] == "bytea"
        rules = dict(conn.execute(text(
            "SELECT tc.table_name || '.' || kcu.column_name, rc.delete_rule FROM information_schema.referential_constraints rc "
            "JOIN information_schema.table_constraints tc ON tc.constraint_name = rc.constraint_name "
            "JOIN information_schema.key_column_usage kcu ON kcu.constraint_name = rc.constraint_name")).all())
        assert rules["attendance_records.session_id"] == "CASCADE"
        assert rules["attendance_records.student_id"] == "RESTRICT"
        assert rules["attendance_recognition_runs.started_by_id"] == "SET NULL"


# ── Concurrency ───────────────────────────────────────────────────────────


class _SlowEngine(FakeEngine):
    def __init__(self, delay=1.5):
        super().__init__()
        self.delay, self.analyzing = delay, threading.Event()

    def analyze(self, image_bgr, *, purpose):
        if purpose == "classroom":
            self.analyzing.set()
            time.sleep(self.delay)
        return super().analyze(image_bgr, purpose=purpose)


@pytest.fixture()
def slow_engine():
    engine = _SlowEngine()
    face_model.set_engine(engine)
    return engine


def _photo_session(client, teacher_h, rc, engine):  # noqa: F811
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], engine, 900, 600, [with_similarity(rc["vec"]["F23CSE01"], 0.9)])
    return client.get(f"{API}/attendance/sessions/{s['id']}", headers=teacher_h).json()


def test_two_simultaneous_recognition_runs_start_only_one(client, teacher_h, rc, slow_engine, db_session):  # noqa: F811
    s = _photo_session(client, teacher_h, rc, slow_engine)
    codes = sorted(r.status_code for r in parallel(lambda: run(client, teacher_h, s), lambda: run(client, teacher_h, s)))
    assert codes == [200, 409]
    with db_session() as db:
        runs = db.scalars(select(AttendanceRecognitionRun).where(AttendanceRecognitionRun.session_id == s["id"])).all()
        assert len(runs) == 1 and runs[0].status == RecognitionRunStatus.COMPLETED_WITH_WARNINGS


def test_many_concurrent_run_requests_still_start_one(client, teacher_h, rc, slow_engine, db_session):  # noqa: F811
    s = _photo_session(client, teacher_h, rc, slow_engine)
    results = parallel(*[lambda: run(client, teacher_h, s)] * 6)
    assert sorted(r.status_code for r in results).count(200) == 1
    with db_session() as db:
        assert db.scalar(select(func.count(AttendanceRecognitionRun.id))) == 1


def test_database_rejects_a_second_processing_run_from_another_connection(rc, db_session):
    sid = rc["session"]["id"]

    def insert():
        with db_session() as db:
            db.add(AttendanceRecognitionRun(session_id=sid, status=RecognitionRunStatus.PROCESSING, started_at=datetime.now(UTC),
                                            model_name="m", model_version="v", image_count=1))
            try:
                db.commit()
                return "ok"
            except IntegrityError:
                return "conflict"

    assert sorted(parallel(insert, insert)) == ["conflict", "ok"]


def test_finalize_and_discard_are_refused_while_recognition_runs(client, teacher_h, rc, slow_engine, db_session):  # noqa: F811
    s = _photo_session(client, teacher_h, rc, slow_engine)
    s = client.post(f"{API}/attendance/sessions/{s['id']}/bulk", headers=teacher_h,
                    json={"version": s["version"], "action": "all_absent"}).json()
    with ThreadPoolExecutor(1) as pool:
        running = pool.submit(run, client, teacher_h, s)
        assert slow_engine.analyzing.wait(10)
        fin = finalize(client, teacher_h, s)
        cancel = client.post(f"{API}/attendance/sessions/{s['id']}/cancel", headers=teacher_h, json={"version": s["version"]})
        done = running.result(timeout=60)
    assert fin.status_code == 409 and "still running" in fin.json()["detail"]
    assert cancel.status_code == 409
    assert done.status_code == 200
    final = finalize(client, teacher_h, done.json()["session"])
    assert final.status_code == 200 and final.json()["status"] == "finalized"


def test_finalize_racing_the_apply_step_never_finalizes_a_changed_session(client, teacher_h, rc, slow_engine,  # noqa: F811
                                                                          db_session, monkeypatch):
    """Finalize validated against version v while the run applies results (v → v+1) at the same
    moment: with the session row locked, exactly one wins and nothing is finalized unreviewed."""
    s = _photo_session(client, teacher_h, rc, slow_engine)
    s = client.post(f"{API}/attendance/sessions/{s['id']}/bulk", headers=teacher_h,
                    json={"version": s["version"], "action": "all_absent"}).json()
    slow_engine.delay = 0
    applying = threading.Barrier(2)
    from backend.app.services import recognition_service

    original_apply = recognition_service._apply

    def apply_slowly(*args, **kwargs):
        try:
            applying.wait(timeout=2)  # finalize is now in flight
        except threading.BrokenBarrierError:
            pass
        time.sleep(0.5)
        return original_apply(*args, **kwargs)

    original_check = attendance_service._no_recognition_running

    def check_then_signal(db, session, message):
        original_check(db, session, message)
        if "finalizing" in message:
            try:
                applying.wait(timeout=2)
            except threading.BrokenBarrierError:
                pass

    monkeypatch.setattr(recognition_service, "_apply", apply_slowly)
    monkeypatch.setattr(attendance_service, "_no_recognition_running", check_then_signal)
    # Start the run first so it is past its own checks; finalize arrives during the apply.
    with ThreadPoolExecutor(1) as pool:
        running = pool.submit(run, client, teacher_h, s)
        while True:
            with db_session() as db:
                r = db.scalar(select(AttendanceRecognitionRun))
                if r is not None and r.stage == "saving":
                    break
            time.sleep(0.02)
        monkeypatch.setattr(recognition_service, "active_run", lambda db, sid: None)  # let finalize past the guard
        fin = finalize(client, teacher_h, s)
        done = running.result(timeout=60)
    with db_session() as db:
        session = db.get(AttendanceSession, s["id"])
        unmarked = db.scalar(select(func.count(AttendanceRecord.id)).where(
            AttendanceRecord.session_id == s["id"], AttendanceRecord.status.is_(None)))
    outcomes = (fin.status_code, done.status_code)
    assert outcomes in ((409, 200), (200, 409)), outcomes
    if session.status == SessionStatus.FINALIZED:
        assert unmarked == 0


def test_two_simultaneous_edits_with_the_same_version_cannot_both_win(client, teacher_h, rc, db_session, monkeypatch):  # noqa: F811
    s = rc["session"]
    both_checked = threading.Barrier(2)
    original_bump = attendance_service._bump

    def bump_together(session):
        try:
            both_checked.wait(timeout=1.5)  # without a row lock both requests get here with version v
        except threading.BrokenBarrierError:
            pass
        original_bump(session)

    monkeypatch.setattr(attendance_service, "_bump", bump_together)
    a, b = rec_of(s, "F23CSE01"), rec_of(s, "F23CSE04")

    def edit(record_id, status_):
        return client.patch(f"{API}/attendance/sessions/{s['id']}/records", headers=teacher_h,
                            json={"version": s["version"], "changes": [{"record_id": record_id, "status": status_}]})

    results = parallel(lambda: edit(a["id"], "present"), lambda: edit(a["id"], "absent"))
    assert sorted(r.status_code for r in results) == [200, 409]
    winner = next(r for r in results if r.status_code == 200).json()
    with db_session() as db:
        session = db.get(AttendanceSession, s["id"])
        stored = db.get(AttendanceRecord, a["id"]).status.value
    assert session.version == s["version"] + 1 == winner["version"]
    assert stored == rec_of(winner, "F23CSE01")["status"]
    del b


def test_concurrent_start_of_the_same_slot_creates_one_session(client, teacher_h, rc, db_session):  # noqa: F811
    body = {"assignment_id": rc["assignment"], "session_date": TODAY, "session_number": 3}
    results = parallel(*[lambda: client.post(f"{API}/attendance/sessions", headers=teacher_h, json=body)] * 4)
    codes = sorted(r.status_code for r in results)
    assert codes.count(201) == 1 and all(c in (200, 201) for c in codes), codes  # the others resume the same draft
    assert len({r.json()["session"]["id"] for r in results}) == 1
    with db_session() as db:
        [sid] = db.scalars(select(AttendanceSession.id).where(AttendanceSession.session_number == 3)).all()
        assert db.scalar(select(func.count(AttendanceRecord.id)).where(
            AttendanceRecord.session_id == sid)) == len(results[0].json()["session"]["records"])


def test_duplicate_enrollments_are_prevented_under_concurrency(client, hod_h, ids, db_session, login):
    teacher = login("teacher.cse@smartclass.edu")
    student = client.post(f"{API}/students", headers=hod_h, json={
        "full_name": "Race Student", "email": "race@test.edu", "password": "Student@123", "registration_no": "F23CSE77",
        "batch_id": ids["batch"], "semester_id": ids["semester"], "section_id": ids["section_a"]}).json()
    with db_session() as db:
        assignment = db.scalar(select(TeacherCourseAssignment.id).where(
            TeacherCourseAssignment.course_id == ids["courses"]["CS-321"],
            TeacherCourseAssignment.section_id == ids["section_a"]))
    body = {"assignment_id": assignment, "student_id": student["id"]}
    results = parallel(*[lambda: client.post(f"{API}/enrollments", headers=teacher, json=body)] * 4)
    codes = sorted(r.status_code for r in results)
    assert codes.count(201) == 1 and set(codes) <= {201, 409}, codes
    assert all("Traceback" not in r.text and "psycopg" not in r.text for r in results)
    with db_session() as db:
        assert db.scalar(select(func.count(StudentCourseEnrollment.id)).where(
            StudentCourseEnrollment.student_id == student["id"])) == 1


def test_duplicate_teacher_assignments_are_prevented_under_concurrency(client, hod_h, ids, db_session):
    body = {"teacher_id": ids["teacher"], "course_id": ids["courses"]["MA-301"], "section_id": ids["section_b"]}
    results = parallel(*[lambda: client.post(f"{API}/assignments", headers=hod_h, json=body)] * 4)
    codes = sorted(r.status_code for r in results)
    assert codes.count(201) == 1 and set(codes) <= {201, 409}, codes
    with db_session() as db:
        assert db.scalar(select(func.count(TeacherCourseAssignment.id)).where(
            TeacherCourseAssignment.course_id == ids["courses"]["MA-301"],
            TeacherCourseAssignment.section_id == ids["section_b"])) == 1


def _finalized(client, teacher_h, rc):  # noqa: F811
    s = rc["session"]
    s = client.post(f"{API}/attendance/sessions/{s['id']}/bulk", headers=teacher_h,
                    json={"version": s["version"], "action": "all_present"}).json()
    return finalize(client, teacher_h, s).json()


def test_delete_attendance_is_all_or_nothing(client, teacher_h, rc, db_session, monkeypatch):  # noqa: F811
    final = _finalized(client, teacher_h, rc)

    def fail(*_a, **_k):
        raise RuntimeError("simulated failure after the deletes")

    monkeypatch.setattr(attendance_service, "record_audit", fail)
    with pytest.raises(RuntimeError, match="simulated"):  # (the API turns this into a plain 500)
        client.post(f"{API}/attendance/sessions/{final['id']}/delete", headers=teacher_h,
                    json={"reason": "Entered for the wrong class"})
    with db_session() as db:
        assert db.get(AttendanceSession, final["id"]) is not None
        assert db.scalar(select(func.count(AttendanceRecord.id)).where(
            AttendanceRecord.session_id == final["id"])) == len(final["records"])


def test_concurrent_deletes_and_a_correction_leave_no_partial_state(client, teacher_h, rc, db_session):  # noqa: F811
    final = _finalized(client, teacher_h, rc)
    record = final["records"][0]

    def delete():
        return client.post(f"{API}/attendance/sessions/{final['id']}/delete", headers=teacher_h,
                           json={"reason": "Entered for the wrong class"})

    def correct():
        return client.post(f"{API}/attendance/records/{record['id']}/correct", headers=teacher_h,
                           json={"status": "absent", "reason": "Left early"})

    results = parallel(delete, delete, correct)
    deletes = sorted(r.status_code for r in results[:2])
    assert deletes == [204, 404], deletes  # the second delete finds nothing
    assert results[2].status_code in (200, 404)
    with db_session() as db:
        assert db.get(AttendanceSession, final["id"]) is None
        assert db.scalar(select(func.count(AttendanceRecord.id)).where(
            AttendanceRecord.session_id == final["id"])) == 0


# ── Timezones ─────────────────────────────────────────────────────────────


def test_session_timezone_of_the_database_does_not_change_results(client, teacher_h, rc, db_session):  # noqa: F811
    """PostgreSQL returns timestamptz in the connection's TimeZone; instants (and the API output)
    must be identical whatever that setting is."""
    final = _finalized(client, teacher_h, rc)
    seen = {}
    for tz in ("UTC", "Asia/Karachi", "America/Los_Angeles"):
        engine = create_engine(TEST_DATABASE_URL, connect_args={"options": f"-c timezone={tz}"})
        with engine.connect() as conn:
            seen[tz] = conn.execute(text("SELECT finalized_at FROM attendance_sessions WHERE id = :i"),
                                    {"i": final["id"]}).scalar_one()
        engine.dispose()
    assert seen["UTC"] == seen["Asia/Karachi"] == seen["America/Los_Angeles"]  # same instant
    assert {v.utcoffset() for v in seen.values()} == {timedelta(0), timedelta(hours=5), seen["America/Los_Angeles"].utcoffset()}
    api_value = datetime.fromisoformat(final["finalized_at"])
    assert api_value.tzinfo is not None and abs(api_value - seen["UTC"]) < timedelta(seconds=1)


def test_correction_window_is_computed_on_instants(client, teacher_h, rc, db_session):  # noqa: F811
    final = _finalized(client, teacher_h, rc)
    record = final["records"][0]
    with db_session() as db:
        session = db.get(AttendanceSession, final["id"])
        session.finalized_at = datetime.now(UTC) - timedelta(hours=23, minutes=59)
        db.commit()
    ok = client.post(f"{API}/attendance/records/{record['id']}/correct", headers=teacher_h,
                     json={"status": "absent", "reason": "Left early"})
    assert ok.status_code == 200
    with db_session() as db:
        db.get(AttendanceSession, final["id"]).finalized_at = datetime.now(UTC) - timedelta(hours=24, minutes=1)
        db.commit()
    locked = client.post(f"{API}/attendance/records/{record['id']}/correct", headers=teacher_h,
                         json={"status": "present", "reason": "Was present"})
    assert locked.status_code == 403 and "window" in locked.json()["detail"]


def test_records_ignore_unknown_identities_on_postgres(client, teacher_h, rc, fake_face_engine):  # noqa: F811
    """Smoke of the full recognition path on PostgreSQL (JSONB diagnostics, partial index, locks)."""
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600,
                    [with_similarity(rc["vec"]["F23CSE01"], 0.9), random_identity(5)])
    body = run(client, teacher_h, client.get(f"{API}/attendance/sessions/{s['id']}", headers=teacher_h).json()).json()
    assert body["recognition"]["run"]["diagnostics"]["model"] == fake_face_engine.model_name
    assert [f["category"] for f in body["recognition"]["faces"]] == ["confident", "no_match"]
