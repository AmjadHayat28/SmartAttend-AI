"""Student face embeddings: generation, freshness and invalidation.

Strategy: one embedding per approved registration photo (front, left, right and any extras),
stored L2-normalised. At match time a classroom face is compared with every embedding of a
candidate and the best score counts (see face_recognition/matching.py). No centroid is stored:
with only 3–5 photos the per-photo maximum keeps the pose-specific evidence that averaging
would blur.

Eligibility: account ACTIVE **and** face enrollment APPROVED. Nothing else is ever embedded.

Freshness: a row is valid only if its model name/version match the running engine and its
`source_updated_at` equals the photo's `updated_at`. Stale rows are replaced; rows are deleted
outright when an enrollment is sent back for a retake.

Embeddings are biometric data: they never leave this module except as in-memory arrays for
matching, and are never logged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

import cv2
import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.face_recognition.matching import filter_enrollment_vectors
from backend.app.face_recognition.types import Candidate, FaceEngine
from backend.app.models import (
    AccountStatus,
    FaceEmbedding,
    FaceEnrollmentStatus,
    Student,
    StudentFaceImage,
    User,
)
from backend.app.services import storage

log = logging.getLogger("smartclass.recognition")


@dataclass
class EmbeddingReport:
    student_id: int
    eligible: bool
    created: int = 0
    up_to_date: int = 0
    failed: list[str] = field(default_factory=list)  # human-readable, no biometric data

    @property
    def ok(self) -> bool:
        return self.eligible and not self.failed


def _naive_utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    return ts.astimezone(UTC).replace(tzinfo=None) if ts.tzinfo else ts


def is_eligible(student: Student, user: User | None = None) -> bool:
    user = user or student.user
    return user.status == AccountStatus.ACTIVE and student.face_enrollment_status == FaceEnrollmentStatus.APPROVED


def _is_fresh(row: FaceEmbedding, image: StudentFaceImage, engine: FaceEngine) -> bool:
    return (row.model_name == engine.model_name and row.model_version == engine.model_version
            and row.dimension == engine.dimension
            and _naive_utc(row.source_updated_at) == _naive_utc(image.updated_at))


def decode_bgr(data: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("unreadable image")
    return image


def invalidate_student(db: Session, student_id: int) -> int:
    """Delete every embedding of a student (enrollment rejected / retake requested)."""
    return db.execute(delete(FaceEmbedding).where(FaceEmbedding.student_id == student_id)).rowcount or 0


def generate_for_student(db: Session, student: Student, engine: FaceEngine) -> EmbeddingReport:
    """Create or refresh embeddings for one student. Does not commit."""
    report = EmbeddingReport(student_id=student.id, eligible=is_eligible(student))
    if not report.eligible:
        return report
    images = db.scalars(select(StudentFaceImage).where(
        StudentFaceImage.student_id == student.id, StudentFaceImage.is_usable.is_(True))).all()
    existing = {e.face_image_id: e for e in db.scalars(
        select(FaceEmbedding).where(FaceEmbedding.student_id == student.id))}
    for image in images:
        row = existing.get(image.id)
        if row is not None and _is_fresh(row, image, engine):
            report.up_to_date += 1
            continue
        try:
            faces = engine.analyze(decode_bgr(storage.read(image.image_path)), purpose="enrollment")
        except Exception as exc:  # one bad photo must not stop the others
            report.failed.append(f"{image.image_type.value} photo: could not be processed ({type(exc).__name__})")
            if row is not None:
                db.delete(row)
            continue
        if not faces:
            report.failed.append(f"{image.image_type.value} photo: no face found by the recognition model")
            if row is not None:
                db.delete(row)
            continue
        face = max(faces, key=lambda f: f.bbox[2] * f.bbox[3])  # the student's own (largest) face
        vector = np.asarray(face.embedding, dtype=np.float32)
        if row is None:
            row = FaceEmbedding(student_id=student.id, face_image_id=image.id)
            db.add(row)
        row.embedding_vector = vector.tobytes()
        row.dimension = int(vector.shape[0])
        row.model_name, row.model_version = engine.model_name, engine.model_version
        row.source_updated_at = image.updated_at
        row.det_score = float(face.det_score)
        row.created_at = datetime.now(UTC)
        report.created += 1
    db.flush()
    return report


def load_candidates(db: Session, student_ids: list[int], engine: FaceEngine) -> tuple[list[Candidate], set[int]]:
    """Fresh embeddings for the given (roster) students who are currently eligible.
    Returns (candidates, ids of eligible students without any usable embedding)."""
    if not student_ids:
        return [], set()
    eligible_ids = set(db.scalars(
        select(Student.id).join(User, User.id == Student.user_id).where(
            Student.id.in_(student_ids), User.status == AccountStatus.ACTIVE,
            Student.face_enrollment_status == FaceEnrollmentStatus.APPROVED)))
    rows = db.execute(
        select(FaceEmbedding, StudentFaceImage.updated_at)
        .join(StudentFaceImage, StudentFaceImage.id == FaceEmbedding.face_image_id)
        .where(FaceEmbedding.student_id.in_(eligible_ids), StudentFaceImage.is_usable.is_(True))
    ).all()
    vectors: dict[int, list[np.ndarray]] = {}
    for row, image_updated in rows:
        if (row.model_name != engine.model_name or row.model_version != engine.model_version
                or row.dimension != engine.dimension or _naive_utc(row.source_updated_at) != _naive_utc(image_updated)):
            continue  # stale: never used for matching
        vectors.setdefault(row.student_id, []).append(np.frombuffer(row.embedding_vector, dtype=np.float32))
    candidates = [Candidate(student_id=sid, vectors=filter_enrollment_vectors(
                      np.stack(vs), settings.FACE_ENROLLMENT_MIN_CONSISTENCY)) for sid, vs in sorted(vectors.items())]
    return candidates, eligible_ids - set(vectors)


def ensure_embeddings(db: Session, student_ids: list[int], engine: FaceEngine) -> list[EmbeddingReport]:
    """Create missing / refresh stale embeddings for the eligible students in `student_ids`.
    Photos whose embedding is already fresh are skipped without running the model."""
    if not student_ids:
        return []
    eligible = db.scalars(
        select(Student).join(User, User.id == Student.user_id).where(
            Student.id.in_(student_ids), User.status == AccountStatus.ACTIVE,
            Student.face_enrollment_status == FaceEnrollmentStatus.APPROVED)
    ).all()
    return [generate_for_student(db, student, engine) for student in eligible]


def generate_in_background(bind, student_id: int) -> None:
    """Run after a face enrollment is approved (FastAPI BackgroundTasks). Failures are logged
    and retried automatically by the next recognition run or the backfill script."""
    from backend.app.face_recognition.model import FaceModelUnavailable, get_engine
    from backend.app.core.config import settings

    if not settings.FACE_RECOGNITION_ENABLED:
        return
    with Session(bind=bind) as db:
        student = db.get(Student, student_id)
        if student is None:
            return
        try:
            report = generate_for_student(db, student, get_engine())
            db.commit()
            log.info("embeddings student=%s created=%s up_to_date=%s failed=%s",
                     student_id, report.created, report.up_to_date, len(report.failed))
        except FaceModelUnavailable as exc:
            db.rollback()
            log.warning("embeddings deferred for student=%s: %s", student_id, exc)
        except Exception:  # pragma: no cover - defensive
            db.rollback()
            log.exception("embedding generation failed for student=%s", student_id)
