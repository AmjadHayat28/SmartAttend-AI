"""Development-only threshold calibration for face recognition. Never exposed over HTTP.

Two modes (neither changes any data, neither prints embeddings):

  # 1. Inspect a draft/finalized session's classroom photos against its roster
  uv run python -m backend.app.scripts.calibrate_recognition --session 42

  # 2. Probe images of *volunteers* who are approved students: files named <REGNO>_<anything>.jpg,
  #    one face per image. Reports genuine vs impostor score distributions and suggests thresholds.
  uv run python -m backend.app.scripts.calibrate_recognition --probes D:\\calibration\\probes

Use only images people have agreed to provide for this purpose, and delete them afterwards.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from sqlalchemy import select

from backend.app.core.config import settings


def _fmt(v: float | None) -> str:
    return "  -  " if v is None else f"{v:5.3f}"


def inspect_session(db, engine, session_id: int) -> None:
    from backend.app.face_recognition.matching import match_session
    from backend.app.models import AttendanceRecord, AttendanceSessionImage, Student
    from backend.app.services.face_embedding_service import load_candidates
    from backend.app.services.recognition_service import _analyze, thresholds

    roster = list(db.scalars(select(AttendanceRecord.student_id).where(AttendanceRecord.session_id == session_id)))
    candidates, _ = load_candidates(db, roster, engine)
    regs = dict(db.execute(select(Student.id, Student.registration_no).where(Student.id.in_(roster))).all())
    images = db.scalars(select(AttendanceSessionImage).where(AttendanceSessionImage.session_id == session_id)).all()
    t = thresholds()
    print(f"roster={len(roster)} candidates={len(candidates)} images={len(images)} thresholds={t.as_dict()}")
    faces = [_analyze(engine, img)[0] for img in images]
    results = match_session(faces, candidates, t)
    print(f"{'img':>4} {'face':>4} {'det':>5} {'top1':>12} {'s1':>5} {'top2':>12} {'s2':>5} {'margin':>6}  category")
    for r in results:
        margin = None if r.similarity is None or r.second_similarity is None else r.similarity - r.second_similarity
        print(f"{r.image_id:>4} {r.face_index:>4} {r.det_score:5.2f} {regs.get(r.student_id, '-'):>12} {_fmt(r.similarity)} "
              f"{regs.get(r.second_student_id, '-'):>12} {_fmt(r.second_similarity)} {_fmt(margin)}  {r.category.value}")


def probe(db, engine, folder: Path) -> None:
    from backend.app.models import AccountStatus, FaceEnrollmentStatus, Student, User
    from backend.app.services.face_embedding_service import decode_bgr, load_candidates

    ids = dict(db.execute(select(Student.registration_no, Student.id).join(User, User.id == Student.user_id).where(
        User.status == AccountStatus.ACTIVE, Student.face_enrollment_status == FaceEnrollmentStatus.APPROVED)).all())
    candidates, _ = load_candidates(db, list(ids.values()), engine)
    index = {c.student_id: c for c in candidates}
    genuine, impostor, misses = [], [], 0
    for path in sorted(folder.glob("*.*")):
        reg = path.stem.split("_")[0].upper()
        if reg not in ids or ids[reg] not in index:
            print(f"skip {path.name}: {reg} is not an approved student with embeddings")
            continue
        faces = engine.analyze(decode_bgr(path.read_bytes()), purpose="enrollment")
        if not faces:
            misses += 1
            print(f"{path.name}: no face detected")
            continue
        face = max(faces, key=lambda f: f.bbox[2] * f.bbox[3]).embedding
        own = float(np.max(index[ids[reg]].vectors @ face))
        others = [float(np.max(c.vectors @ face)) for sid, c in index.items() if sid != ids[reg]]
        best_other = max(others) if others else None
        genuine.append(own)
        impostor.extend(others)
        print(f"{path.name}: own={own:.3f} best_other={_fmt(best_other)} margin={_fmt(None if best_other is None else own - best_other)}")
    if not genuine:
        print("No usable probes.")
        return
    g, i = np.array(genuine), np.array(impostor) if impostor else np.array([0.0])
    print(f"\nprobes={len(genuine)} undetected={misses} gallery={len(index)}")
    print(f"genuine:  min={g.min():.3f} p05={np.percentile(g, 5):.3f} median={np.median(g):.3f}")
    print(f"impostor: max={i.max():.3f} p99={np.percentile(i, 99):.3f} median={np.median(i):.3f}")
    low = float(np.percentile(i, 99)) + 0.02
    confident = max(low + 0.08, float(np.percentile(g, 5)))
    print(f"suggested (review before use): FACE_MATCH_LOW~{low:.2f}  FACE_MATCH_CONFIDENT~{confident:.2f}")
    print(f"current:  FACE_MATCH_LOW={settings.FACE_MATCH_LOW}  FACE_MATCH_CONFIDENT={settings.FACE_MATCH_CONFIDENT}  "
          f"MARGIN={settings.FACE_MATCH_AMBIGUITY_MARGIN}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--session", type=int)
    group.add_argument("--probes", type=Path)
    parser.add_argument("--allow-production", action="store_true")
    args = parser.parse_args()
    if settings.ENVIRONMENT == "production" and not args.allow_production:
        print("Refusing to run in production (development diagnostic).")
        return 2

    from backend.app.database.session import SessionLocal
    from backend.app.face_recognition.model import FaceModelUnavailable, get_engine

    try:
        engine = get_engine()
    except FaceModelUnavailable as exc:
        print(f"ERROR: {exc}")
        return 1
    with SessionLocal() as db:
        if args.session:
            inspect_session(db, engine, args.session)
        else:
            if not args.probes.is_dir():
                print(f"Not a folder: {args.probes}")
                return 1
            probe(db, engine, args.probes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
