"""Face recognition for DRAFT attendance sessions — assists the teacher, never decides alone.

Run (teacher clicks "Run Face Recognition"):
  1. Preconditions: own draft, current version, ≥1 classroom photo, roster, ≥1 eligible
     student with embeddings (missing/stale ones are generated first).
  2. Compute everything in memory: detect + embed faces in each photo, match against the
     **session roster only** (see face_recognition/matching.py). Failures here mark the run
     FAILED and leave attendance untouched.
  3. Apply in one transaction:
       - previous *unconfirmed* AI marks (method=face_recognition) are cleared back to "not
         marked" — they are recomputed from scratch;
       - each student's primary CONFIDENT match pre-fills Present (method=face_recognition)
         **only if the record is not marked** — teacher decisions (manual, bulk, or confirmed
         AI) are never overwritten; such faces are recorded as MANUAL_KEPT;
       - LOW_CONFIDENCE / AMBIGUOUS / DUPLICATE faces wait for the teacher (PENDING);
       - students not seen stay exactly as they were (never auto-Absent).
Teacher decisions on the latest run: accept a suggestion, assign a roster student, or reject.
Nothing here finalizes a session.

Job safety (Phase 9): at most one PROCESSING run per session (database unique index); the run
commits its real stage/photo count so the page can show truthful progress; it stops between
photos after FACE_RECOGNITION_TIMEOUT_SECONDS; photos, finalize and discard wait while it runs;
and results are applied only if the session is still a draft. Every failure leaves attendance
unchanged and returns a message that is safe to show (details go to the log).
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.face_recognition.matching import match_session
from backend.app.face_recognition.model import FaceModelUnavailable, get_engine
from backend.app.face_recognition.types import FaceEngine, ImageFaces, Thresholds
from backend.app.models import (
    AttendanceMethod,
    AttendanceRecognitionFace,
    AttendanceRecognitionRun,
    AttendanceRecord,
    AttendanceSession,
    AttendanceSessionImage,
    AttendanceStatus,
    FaceDecision,
    RecognitionCategory,
    RecognitionRunStatus,
    SessionStatus,
    Student,
    User,
    UserRole,
)
from backend.app.schemas.recognition import (
    BoundingBox,
    RecognitionActionOut,
    RecognitionFaceOut,
    RecognitionOut,
    RecognitionRunOut,
    StudentRef,
)
from backend.app.services import storage
from backend.app.services.storage import StorageError
from backend.app.services.attendance_service import (
    _audit,
    _bump,
    _editable_session,
    _get_session,
    session_detail,
)
from backend.app.services.face_embedding_service import decode_bgr, ensure_embeddings, load_candidates

log = logging.getLogger("smartclass.recognition")

_AI_METHODS = (AttendanceMethod.FACE_RECOGNITION, AttendanceMethod.FACE_RECOGNITION_CONFIRMED)
_LINKED = (FaceDecision.APPLIED, FaceDecision.ACCEPTED, FaceDecision.ASSIGNED)

# Safe, teacher-facing messages. Technical detail goes to the log and the audit trail only.
MODEL_UNAVAILABLE = ("Face recognition is not available right now: the recognition model is not installed or "
                     "could not be loaded. Attendance was not changed — you can still mark students manually. "
                     "Please tell the administrator.")
ALREADY_RUNNING = "Face recognition is already running for this session. Wait for it to finish."
INTERRUPTED = "Recognition was interrupted before it finished. Attendance was not changed — run it again."


class _RunAborted(Exception):
    """Stops a run with a message that is safe to show the teacher."""

    def __init__(self, status_code: int, message: str, reason: str):
        super().__init__(message)
        self.status_code, self.message, self.reason = status_code, message, reason


def _now() -> datetime:
    return datetime.now(UTC)


def _stale_after_seconds() -> int:
    """A PROCESSING run older than this was interrupted (server restart, crash): every live run
    stops itself at FACE_RECOGNITION_TIMEOUT_SECONDS, plus at most one photo's worth of work."""
    return settings.FACE_RECOGNITION_TIMEOUT_SECONDS + 60


def _is_stale(run: AttendanceRecognitionRun) -> bool:
    started = run.started_at.replace(tzinfo=UTC) if run.started_at.tzinfo is None else run.started_at
    return (_now() - started).total_seconds() >= _stale_after_seconds()


def active_run(db: Session, session_id: int) -> AttendanceRecognitionRun | None:
    """The session's recognition run that is genuinely still in progress, if any."""
    run = _latest_run(db, session_id)
    return run if run is not None and run.status == RecognitionRunStatus.PROCESSING and not _is_stale(run) else None


def thresholds() -> Thresholds:
    return Thresholds(confident=settings.FACE_MATCH_CONFIDENT, low=settings.FACE_MATCH_LOW,
                      margin=settings.FACE_MATCH_AMBIGUITY_MARGIN)


def _clamp(score: float | None) -> float | None:
    return None if score is None else max(0.0, min(1.0, float(score)))


def _latest_run(db: Session, session_id: int) -> AttendanceRecognitionRun | None:
    return db.scalar(select(AttendanceRecognitionRun).where(AttendanceRecognitionRun.session_id == session_id)
                     .order_by(AttendanceRecognitionRun.id.desc()).limit(1))


# ── Read model ─────────────────────────────────────────────────────────────


def recognition_view(db: Session, user: User, session: AttendanceSession) -> RecognitionOut:
    run = _latest_run(db, session.id)
    editable = (session.status == SessionStatus.DRAFT and user.role == UserRole.TEACHER
                and user.teacher_profile is not None and session.teacher_id == user.teacher_profile.id)
    if run is None:
        return RecognitionOut(run=None, faces=[], can_run=editable, can_decide=False)
    faces = db.scalars(select(AttendanceRecognitionFace).where(AttendanceRecognitionFace.run_id == run.id)
                       .order_by(AttendanceRecognitionFace.image_id, AttendanceRecognitionFace.face_index)).all()
    ids = {sid for f in faces for sid in (f.student_id, f.second_student_id, f.assigned_student_id) if sid}
    ids |= set(run.missing_student_ids or [])
    refs = {sid: StudentRef(student_id=sid, registration_no=reg, full_name=name) for sid, reg, name in db.execute(
        select(Student.id, Student.registration_no, User.full_name).join(User, User.id == Student.user_id)
        .where(Student.id.in_(ids)))} if ids else {}
    sizes = dict((i, (w, h)) for i, w, h in db.execute(
        select(AttendanceSessionImage.id, AttendanceSessionImage.width, AttendanceSessionImage.height)
        .where(AttendanceSessionImage.session_id == session.id)))
    starter = db.get(User, run.started_by_id) if run.started_by_id else None
    status_, stage, error = run.status, run.stage, run.error_message
    if status_ == RecognitionRunStatus.PROCESSING and _is_stale(run):
        # Abandoned (e.g. server restart mid-run). Shown as failed so the page never waits forever;
        # the row itself is closed when the next run starts.
        status_, stage, error = RecognitionRunStatus.FAILED, None, INTERRUPTED
    in_progress = status_ == RecognitionRunStatus.PROCESSING
    return RecognitionOut(
        run=RecognitionRunOut(
            id=run.id, status=status_, stage=stage, images_processed=run.images_processed or 0,
            started_at=run.started_at, finished_at=run.finished_at,
            started_by_name=starter.full_name if starter else None, model_name=run.model_name,
            model_version=run.model_version, thresholds=run.thresholds, image_count=run.image_count,
            faces_detected=run.faces_detected, confident_count=run.confident_count,
            low_confidence_count=run.low_confidence_count, ambiguous_count=run.ambiguous_count,
            duplicate_count=run.duplicate_count, unknown_count=run.unknown_count,
            students_recognized=run.students_recognized, roster_size=run.roster_size,
            eligible_count=run.eligible_count, applied_count=run.applied_count, preserved_count=run.preserved_count,
            missing_students=[refs[s] for s in (run.missing_student_ids or []) if s in refs],
            warnings=run.warnings or [], diagnostics=run.diagnostics, error_message=error,
            is_latest=True,
        ),
        faces=[
            RecognitionFaceOut(
                id=f.id, image_id=f.image_id, image_width=sizes.get(f.image_id, (0, 0))[0],
                image_height=sizes.get(f.image_id, (0, 0))[1], face_index=f.face_index,
                bbox=BoundingBox(x=f.bbox_x, y=f.bbox_y, width=f.bbox_w, height=f.bbox_h), det_score=f.det_score,
                category=f.category, suggested=refs.get(f.student_id) if f.student_id else None,
                similarity=f.similarity, second=refs.get(f.second_student_id) if f.second_student_id else None,
                second_similarity=f.second_similarity, is_primary=f.is_primary, decision=f.decision,
                assigned=refs.get(f.assigned_student_id) if f.assigned_student_id else None,
            )
            for f in faces
        ],
        can_run=editable and not in_progress,
        can_decide=editable and status_ in (RecognitionRunStatus.COMPLETED, RecognitionRunStatus.COMPLETED_WITH_WARNINGS),
    )


def get_recognition(db: Session, user: User, session_id: int) -> RecognitionOut:
    return recognition_view(db, user, _get_session(db, user, session_id))


def _action_out(db: Session, user: User, session: AttendanceSession) -> RecognitionActionOut:
    return RecognitionActionOut(recognition=recognition_view(db, user, session), session=session_detail(db, user, session))


# ── Run ────────────────────────────────────────────────────────────────────


def run_recognition(db: Session, user: User, session_id: int, version: int, request: Request) -> RecognitionActionOut:
    if not settings.FACE_RECOGNITION_ENABLED:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Face recognition is turned off on this server. Please mark attendance manually.")
    session = _editable_session(db, user, session_id, version)
    images = db.scalars(select(AttendanceSessionImage).where(AttendanceSessionImage.session_id == session.id)
                        .order_by(AttendanceSessionImage.id)).all()
    if not images:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Upload at least one classroom photo first.")
    latest = _latest_run(db, session.id)
    if latest is not None and latest.status == RecognitionRunStatus.PROCESSING:
        if not _is_stale(latest):
            raise HTTPException(status.HTTP_409_CONFLICT, ALREADY_RUNNING)
        latest.status, latest.stage, latest.finished_at = RecognitionRunStatus.FAILED, None, _now()
        latest.error_message = INTERRUPTED
        db.flush()  # before the new run is inserted (one PROCESSING run per session)

    roster_ids = list(db.scalars(select(AttendanceRecord.student_id).where(AttendanceRecord.session_id == session.id)))
    try:
        engine = get_engine()
    except FaceModelUnavailable as exc:
        log.warning("recognition refused for session %s: model unavailable (%s)", session.id, exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, MODEL_UNAVAILABLE) from None

    # ── Prepare: every eligible roster student needs fresh embeddings (generated if needed) ──
    started = time.perf_counter()
    reports = ensure_embeddings(db, roster_ids, engine)
    db.commit()
    candidates, missing_eligible = load_candidates(db, roster_ids, engine)
    if not candidates:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "No students in this class have approved face recognition profiles yet.")
    missing = sorted(set(roster_ids) - {c.student_id for c in candidates})
    prepare_ms = (time.perf_counter() - started) * 1000

    t = thresholds()
    run = AttendanceRecognitionRun(
        session_id=session.id, status=RecognitionRunStatus.PROCESSING, stage="detecting", images_processed=0,
        started_by_id=user.id, started_at=_now(), model_name=engine.model_name, model_version=engine.model_version,
        thresholds=t.as_dict(), image_count=len(images), roster_size=len(roster_ids), eligible_count=len(candidates),
        missing_student_ids=missing,
    )
    db.add(run)
    try:
        db.flush()
    except IntegrityError:  # another request started a run for this session a moment ago
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, ALREADY_RUNNING) from None
    _audit(db, user, request, "recognition.run_started", session,
           new={"run_id": run.id, "images": len(images), "roster": len(roster_ids), "eligible": len(candidates)})
    db.commit()
    run_id = run.id

    # ── 1. Compute (no attendance changes yet). Progress is committed so the page can show it. ──
    warnings = [f"{len(missing)} student(s) on the roster cannot be recognised automatically."] if missing else []
    warnings += [f"Embedding problem — {msg}" for r in reports for msg in r.failed]
    fallback_from = getattr(engine, "fallback_from", None)
    if fallback_from:
        warnings.append(f"The classroom model '{fallback_from}' is unavailable; the fallback "
                        f"'{engine.model_name.split('/')[-1]}' was used (lower accuracy). Ask the administrator.")
    try:
        analysed = []
        for number, image in enumerate(images, start=1):
            analysed.append(_analyze(engine, image, number))
            run.images_processed = number
            db.commit()
            elapsed = time.perf_counter() - started
            if number < len(images) and elapsed > settings.FACE_RECOGNITION_TIMEOUT_SECONDS:
                raise _RunAborted(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    f"Face recognition took too long (over {settings.FACE_RECOGNITION_TIMEOUT_SECONDS} s) and was "
                    "stopped. Attendance was not changed — try again with fewer photos, or mark students manually.",
                    "timeout")
        image_faces = [faces for faces, _ in analysed]
        for number, faces in enumerate(image_faces, start=1):
            if not faces.faces:
                warnings.append(f"No faces were found in classroom photo #{number}. Retake it with faces "
                                "visible, well lit and not too far away.")
        run.stage = "matching"
        db.commit()
        matching_started = time.perf_counter()
        matches = match_session(image_faces, candidates, t)
        run.diagnostics = _diagnostics(engine, [d for _, d in analysed], started, matching_started, prepare_ms,
                                       sum(r.created for r in reports))
        run.stage = "saving"
        db.commit()
    except _RunAborted as exc:
        _fail_run(db, user, request, session, run_id, exc.message, exc.reason)
        log.warning("recognition run %s stopped: %s", run_id, exc.reason)
        raise HTTPException(exc.status_code, exc.message) from None
    except Exception as exc:
        _fail_run(db, user, request, session, run_id,
                  "Recognition failed unexpectedly. Attendance was not changed.", type(exc).__name__)
        log.exception("recognition run %s failed", run_id)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            "Face recognition failed. Your attendance was not changed; please try again.") from None

    # ── 2. Apply atomically — only to a session that is still a draft ──
    db.refresh(session, with_for_update=True)  # row lock where supported (PostgreSQL)
    if session.status != SessionStatus.DRAFT:  # finalized/discarded elsewhere while this run was computing
        message = (f"This attendance was {session.status.value} while recognition was running, so the results "
                   "were not applied. Attendance was not changed.")
        _fail_run(db, user, request, session, run_id, message, f"session_{session.status.value}")
        raise HTTPException(status.HTTP_409_CONFLICT, message)
    try:
        _apply(db, user, session, run, matches)
        run.status = RecognitionRunStatus.COMPLETED_WITH_WARNINGS if warnings else RecognitionRunStatus.COMPLETED
        run.warnings, run.finished_at, run.stage = warnings, _now(), None
        session.faces_detected = run.faces_detected
        _bump(session)
        _audit(db, user, request, "recognition.run_completed", session, new={
            "run_id": run.id, "faces": run.faces_detected, "confident": run.confident_count,
            "low_confidence": run.low_confidence_count, "ambiguous": run.ambiguous_count,
            "duplicate": run.duplicate_count, "unknown": run.unknown_count, "applied": run.applied_count,
            "preserved": run.preserved_count, "model": run.model_name, "thresholds": run.thresholds,
            "fallback_from": (run.diagnostics or {}).get("fallback_from")})
        db.commit()
    except Exception as exc:
        _fail_run(db, user, request, session, run_id,
                  "Results could not be saved. Attendance was not changed.", type(exc).__name__)
        log.exception("recognition run %s apply failed", run_id)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            "Face recognition results could not be saved. Attendance was not changed.") from None
    _log_diagnostics(run, matches)
    return _action_out(db, user, session)


def _fail_run(db: Session, user: User, request: Request, session: AttendanceSession, run_id: int, message: str,
              reason: str) -> None:
    """Close a run as FAILED. Everything uncommitted (incl. any partial attendance) is rolled back
    first; the session's records and version stay exactly as before the run."""
    db.rollback()
    run = db.get(AttendanceRecognitionRun, run_id)
    run.status, run.stage, run.finished_at, run.error_message = RecognitionRunStatus.FAILED, None, _now(), message
    _audit(db, user, request, "recognition.run_failed", session, new={"run_id": run_id, "error": reason})
    db.commit()


def _analyze(engine: FaceEngine, image: AttendanceSessionImage, number: int) -> tuple[ImageFaces, dict]:
    """Faces of one classroom photo (boxes in the stored photo's pixels) + per-photo diagnostics."""
    started = time.perf_counter()
    try:
        bgr = decode_bgr(storage.read(image.image_path))
    except (StorageError, ValueError, OSError):
        log.warning("classroom photo %s (image id %s) could not be read", number, image.id)
        raise _RunAborted(status.HTTP_422_UNPROCESSABLE_CONTENT,
                          f"Classroom photo #{number} could not be read. Remove it, upload it again, and re-run "
                          "recognition. Attendance was not changed.", "unreadable_photo") from None
    decoded = time.perf_counter()
    info: dict = {"decode_ms": round((decoded - started) * 1000, 1)}
    if hasattr(engine, "analyze_classroom"):
        analysis = engine.analyze_classroom(bgr)
        faces, det = analysis.faces, analysis.detection
        info.update(rotation=det.rotation, tiles=det.tiles, merged_duplicates=det.merged_duplicates, passes=det.passes,
                    detection_ms=round(det.detection_ms), recognition_ms=round(analysis.embedding_ms),
                    stage_ms=det.stage_ms)
    else:  # engines without the classroom pipeline (e.g. test doubles): one combined timing
        faces = engine.analyze(bgr, purpose="classroom")
        info.update(detection_ms=round((time.perf_counter() - decoded) * 1000), recognition_ms=0)
    keep = [f for f in faces if f.det_score >= settings.FACE_RECOGNITION_MIN_DET_SCORE
            and min(f.bbox[2], f.bbox[3]) >= settings.FACE_RECOGNITION_MIN_FACE_PX]
    info.update(image_id=image.id, faces=len(keep), filtered=len(faces) - len(keep))
    return ImageFaces(image_id=image.id, faces=keep), info


def _diagnostics(engine: FaceEngine, images: list[dict], started: float, matching_started: float,
                 prepare_ms: float, enrollment_photos_processed: int) -> dict:
    """Non-sensitive run metadata: what ran and how long it took. No vectors, pixels or paths."""
    now = time.perf_counter()
    stages = {k: round(sum(i.get("stage_ms", {}).get(k, 0.0) for i in images)) for k in ("orient", "full", "tiles")}
    return {
        "model": engine.model_name,
        "configured_model": settings.FACE_RECOGNITION_MODEL,
        "fallback_from": getattr(engine, "fallback_from", None),
        "fallback_used": bool(getattr(engine, "fallback_from", None)),
        "detector": getattr(engine, "detector_name", "unknown"),
        "prepare_ms": round(prepare_ms),  # roster profiles (+ any embeddings generated now)
        "enrollment_photos_processed": enrollment_photos_processed,
        "decode_ms": round(sum(i["decode_ms"] for i in images)),
        "detection_ms": sum(i["detection_ms"] for i in images),
        "detection_stages_ms": stages,  # orientation check / full image / tiles
        "recognition_ms": sum(i["recognition_ms"] for i in images),
        "matching_ms": round((now - matching_started) * 1000, 1),
        "total_ms": round((now - started) * 1000),
        "settings": {"tiling": settings.FACE_RECOGNITION_TILING, "auto_orient": settings.FACE_RECOGNITION_AUTO_ORIENT,
                     "min_det_score": settings.FACE_RECOGNITION_MIN_DET_SCORE,
                     "min_face_px": settings.FACE_RECOGNITION_MIN_FACE_PX},
        "images": images,
    }


def _apply(db: Session, user: User, session: AttendanceSession, run: AttendanceRecognitionRun, matches) -> None:
    records = {r.student_id: r for r in db.scalars(
        select(AttendanceRecord).where(AttendanceRecord.session_id == session.id))}
    # Unconfirmed AI marks from earlier runs are recomputed from scratch.
    for record in records.values():
        if record.method == AttendanceMethod.FACE_RECOGNITION:
            record.status, record.method, record.confidence = None, AttendanceMethod.MANUAL, None
            record.recognition_run_id = record.recognition_face_id = None
    db.flush()

    counts = dict.fromkeys(RecognitionCategory, 0)
    recognized: set[int] = set()
    applied, preserved = [], 0
    for m in matches:
        counts[m.category] += 1
        decision = FaceDecision.NONE
        assigned = None
        if m.category == RecognitionCategory.CONFIDENT:
            recognized.add(m.student_id)
            if m.is_primary:
                record = records.get(m.student_id)
                if record is not None and record.status is None:
                    decision, assigned = FaceDecision.APPLIED, m.student_id
                else:
                    decision = FaceDecision.MANUAL_KEPT  # the teacher's decision stands
                    preserved += 1
        elif m.category in (RecognitionCategory.LOW_CONFIDENCE, RecognitionCategory.AMBIGUOUS,
                            RecognitionCategory.DUPLICATE):
            decision = FaceDecision.PENDING
        face = AttendanceRecognitionFace(
            run_id=run.id, image_id=m.image_id, face_index=m.face_index, bbox_x=m.bbox[0], bbox_y=m.bbox[1],
            bbox_w=m.bbox[2], bbox_h=m.bbox[3], det_score=round(m.det_score, 4), category=m.category,
            student_id=m.student_id, similarity=_round(m.similarity), second_student_id=m.second_student_id,
            second_similarity=_round(m.second_similarity), is_primary=m.is_primary, decision=decision,
            assigned_student_id=assigned,
        )
        db.add(face)
        if decision == FaceDecision.APPLIED:
            db.flush()
            record = records[m.student_id]
            record.status, record.method = AttendanceStatus.PRESENT, AttendanceMethod.FACE_RECOGNITION
            record.confidence, record.recognition_run_id, record.recognition_face_id = _clamp(m.similarity), run.id, face.id
            record.last_modified_by_id = user.id
            applied.append(m.student_id)
    run.faces_detected = len(matches)
    run.confident_count = counts[RecognitionCategory.CONFIDENT]
    run.low_confidence_count = counts[RecognitionCategory.LOW_CONFIDENCE]
    run.ambiguous_count = counts[RecognitionCategory.AMBIGUOUS]
    run.duplicate_count = counts[RecognitionCategory.DUPLICATE]
    run.unknown_count = counts[RecognitionCategory.NO_MATCH]
    run.students_recognized, run.applied_count, run.preserved_count = len(recognized), len(applied), preserved
    if applied:
        _audit(db, user, None, "recognition.matches_applied", session,
               new={"run_id": run.id, "student_ids": sorted(applied)})


def _round(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


def _log_diagnostics(run: AttendanceRecognitionRun, matches) -> None:
    """Scores and margins for threshold tuning — never vectors, never images."""
    d = run.diagnostics or {}
    log.info("run=%s model=%s fallback_from=%s faces=%s confident=%s low=%s ambiguous=%s duplicate=%s unknown=%s "
             "thresholds=%s detection_ms=%s recognition_ms=%s matching_ms=%s total_ms=%s",
             run.id, run.model_name, d.get("fallback_from"), run.faces_detected, run.confident_count,
             run.low_confidence_count, run.ambiguous_count, run.duplicate_count, run.unknown_count, run.thresholds,
             d.get("detection_ms"), d.get("recognition_ms"), d.get("matching_ms"), d.get("total_ms"))
    for m in matches:
        log.debug("run=%s image=%s face=%s category=%s top=%.3f second=%s",
                  run.id, m.image_id, m.face_index, m.category.value, m.similarity or -1,
                  f"{m.second_similarity:.3f}" if m.second_similarity is not None else "-")


# ── Teacher decisions on the latest run ────────────────────────────────────


def _decidable_face(db: Session, user: User, face_id: int, version: int):
    face = db.get(AttendanceRecognitionFace, face_id)
    run = db.get(AttendanceRecognitionRun, face.run_id) if face else None
    if face is None or run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Face not found")
    session = _editable_session(db, user, run.session_id, version)  # own draft + version check
    latest = _latest_run(db, session.id)
    if latest is None or latest.id != run.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "These results were replaced by a newer recognition run. Reload.")
    return face, run, session


def _unlink_record(db: Session, session: AttendanceSession, face: AttendanceRecognitionFace) -> None:
    """If this face had set a student's record, return that record to "not marked"."""
    if face.assigned_student_id is None:
        return
    record = db.scalar(select(AttendanceRecord).where(AttendanceRecord.session_id == session.id,
                                                      AttendanceRecord.student_id == face.assigned_student_id))
    if record is not None and record.recognition_face_id == face.id and record.method in _AI_METHODS:
        record.status, record.method, record.confidence = None, AttendanceMethod.MANUAL, None
        record.recognition_run_id = record.recognition_face_id = None


def _link(db, user, session, run, face, student_id: int, decision: FaceDecision, replace: bool, request,
          action: str) -> RecognitionActionOut:
    record = db.scalar(select(AttendanceRecord).where(AttendanceRecord.session_id == session.id,
                                                      AttendanceRecord.student_id == student_id))
    if record is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Only students on this session's roster can be selected.")
    other = db.scalar(select(AttendanceRecognitionFace).where(
        AttendanceRecognitionFace.run_id == run.id, AttendanceRecognitionFace.id != face.id,
        AttendanceRecognitionFace.assigned_student_id == student_id,
        AttendanceRecognitionFace.decision.in_(_LINKED)))
    if other is not None:
        if not replace:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "This student is already matched to another face. Confirm to move the match here.")
        _unlink_record(db, session, other)
        other.decision, other.assigned_student_id = FaceDecision.REJECTED, None
        other.decided_by_id, other.decided_at = user.id, _now()
    if face.assigned_student_id not in (None, student_id):
        _unlink_record(db, session, face)
    previous = {"status": record.status.value if record.status else None, "method": record.method.value}
    record.status, record.method = AttendanceStatus.PRESENT, AttendanceMethod.FACE_RECOGNITION_CONFIRMED
    score = face.similarity if student_id == face.student_id else (
        face.second_similarity if student_id == face.second_student_id else None)
    record.confidence, record.recognition_run_id, record.recognition_face_id = _clamp(score), run.id, face.id
    record.last_modified_by_id = user.id
    face.decision, face.assigned_student_id = decision, student_id
    face.decided_by_id, face.decided_at = user.id, _now()
    _bump(session)
    _audit(db, user, request, action, session, old=previous, new={
        "face_id": face.id, "student_id": student_id, "similarity": score, "category": face.category.value,
        "moved_from_face": other.id if other is not None else None})
    db.commit()
    return _action_out(db, user, session)


def accept(db: Session, user: User, face_id: int, version: int, request: Request) -> RecognitionActionOut:
    face, run, session = _decidable_face(db, user, face_id, version)
    if face.student_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "This face has no suggested student. Choose one instead.")
    return _link(db, user, session, run, face, face.student_id, FaceDecision.ACCEPTED, False, request,
                 "recognition.suggestion_accepted")


def assign(db: Session, user: User, face_id: int, student_id: int, version: int, replace: bool,
           request: Request) -> RecognitionActionOut:
    face, run, session = _decidable_face(db, user, face_id, version)
    return _link(db, user, session, run, face, student_id, FaceDecision.ASSIGNED, replace, request,
                 "recognition.face_assigned")


def reject(db: Session, user: User, face_id: int, version: int, request: Request) -> RecognitionActionOut:
    face, run, session = _decidable_face(db, user, face_id, version)
    _unlink_record(db, session, face)
    old = {"decision": face.decision.value, "student_id": face.assigned_student_id or face.student_id}
    face.decision, face.assigned_student_id = FaceDecision.REJECTED, None
    face.decided_by_id, face.decided_at = user.id, _now()
    _bump(session)
    _audit(db, user, request, "recognition.suggestion_rejected", session, old=old, new={"face_id": face.id})
    db.commit()
    return _action_out(db, user, session)

