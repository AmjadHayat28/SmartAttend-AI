"""Generate or refresh face embeddings for every eligible student (safe to re-run).

    uv run python -m backend.app.scripts.generate_face_embeddings

Eligible = account ACTIVE and face enrollment APPROVED. Up-to-date students are skipped; one
student's failure never stops the batch. Embeddings left behind by students who are no longer
approved are removed. No embedding values are printed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.face_recognition.types import FaceEngine
from backend.app.models import FaceEmbedding, FaceEnrollmentStatus, Student
from backend.app.services.face_embedding_service import generate_for_student, invalidate_student, is_eligible


@dataclass
class BackfillSummary:
    eligible: int = 0
    processed: int = 0  # students that needed new/refreshed embeddings
    skipped: int = 0  # already up to date
    successful: int = 0
    failed: int = 0
    purged_students: int = 0  # no longer approved: embeddings removed
    failures: list[str] = field(default_factory=list)


def backfill(db: Session, engine: FaceEngine) -> BackfillSummary:
    summary = BackfillSummary()
    # Safety net: no embeddings may remain for students whose enrollment is not approved.
    stray = set(db.scalars(select(FaceEmbedding.student_id).join(Student, Student.id == FaceEmbedding.student_id)
                           .where(Student.face_enrollment_status != FaceEnrollmentStatus.APPROVED)))
    for sid in stray:
        invalidate_student(db, sid)
    summary.purged_students = len(stray)
    db.commit()

    for student in db.scalars(select(Student).where(Student.face_enrollment_status == FaceEnrollmentStatus.APPROVED)):
        if not is_eligible(student):
            continue  # e.g. suspended account: kept, but never generated or used
        summary.eligible += 1
        try:
            report = generate_for_student(db, student, engine)
            db.commit()
        except Exception as exc:  # one student must not stop the batch
            db.rollback()
            summary.failed += 1
            summary.failures.append(f"{student.registration_no}: {type(exc).__name__}")
            continue
        if report.created == 0 and not report.failed:
            summary.skipped += 1
            continue
        summary.processed += 1
        if report.failed:
            summary.failed += 1
            summary.failures += [f"{student.registration_no}: {msg}" for msg in report.failed]
        else:
            summary.successful += 1
    return summary


def main() -> int:
    from backend.app.database.session import SessionLocal
    from backend.app.face_recognition.model import FaceModelUnavailable, get_engine

    logging.basicConfig(level=logging.WARNING)
    try:
        engine = get_engine()
    except FaceModelUnavailable as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Model: {engine.model_name} ({engine.model_version}, {engine.dimension}-d)")
    with SessionLocal() as db:
        s = backfill(db, engine)
    print(f"eligible students: {s.eligible}\nprocessed: {s.processed}\nskipped (up to date): {s.skipped}\n"
          f"successful: {s.successful}\nfailed: {s.failed}\npurged (no longer approved): {s.purged_students}")
    for line in s.failures:
        print(f"  - {line}")
    return 1 if s.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
