"""Development-only face recognition benchmark on a LABELLED dataset. Never exposed over HTTP,
never writes to the database, never prints embeddings.

    uv run python -m backend.app.scripts.benchmark_recognition <dataset> [--packs buffalo_l buffalo_sc]
        [--variants baseline,full] [--json out.json]

Dataset layout (use only images people agreed to provide, and delete them afterwards):

    <dataset>/enroll/<LABEL>/*.jpg     enrollment photos per person (one face each)
    <dataset>/images/*.jpg             classroom / group photos
    <dataset>/labels.json              {"<image file>": {"roster": ["LABEL", ...],          # who could be matched
                                                          "visible_faces": 9,                # optional, approximate
                                                          "faces": [{"box": [x, y, w, h],    # original pixels
                                                                     "label": "LABEL" | null}]}}
                                        label null = a person who is NOT on the roster (must stay unknown)

Variants: "baseline" = full-image multi-scale only (the previous pipeline);
          "full"     = + automatic orientation + native-resolution tiles (current defaults).
Per image the production code is used: InsightFaceEngine.analyze_classroom + matching.match_image
with the configured thresholds, and the same enrollment embedding filter as the live system.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from backend.app.core.config import settings

VARIANTS = {
    "baseline": {"FACE_RECOGNITION_TILING": False, "FACE_RECOGNITION_AUTO_ORIENT": False},
    "orient": {"FACE_RECOGNITION_TILING": False, "FACE_RECOGNITION_AUTO_ORIENT": True},
    "tiles": {"FACE_RECOGNITION_TILING": True, "FACE_RECOGNITION_AUTO_ORIENT": False},
    "full": {"FACE_RECOGNITION_TILING": True, "FACE_RECOGNITION_AUTO_ORIENT": True},
}


def _iou(a, b) -> float:
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw, ih = max(0, min(ax2, bx2) - max(a[0], b[0])), max(0, min(ay2, by2) - max(a[1], b[1]))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union else 0.0


def _read(path: Path) -> np.ndarray:
    import cv2

    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"unreadable image {path}")
    return img


def enroll(engine, folder: Path) -> tuple[dict[str, np.ndarray], dict[str, dict]]:
    """label → stacked unit embeddings (after the live outlier filter), plus quality stats."""
    from backend.app.face_recognition.matching import filter_enrollment_vectors

    vectors, stats = {}, {}
    for person in sorted(p for p in (folder / "enroll").iterdir() if p.is_dir()):
        vs = []
        for photo in sorted(person.glob("*.jp*g")) + sorted(person.glob("*.png")):
            faces = engine.analyze(_read(photo), purpose="enrollment")
            if faces:
                vs.append(max(faces, key=lambda f: f.bbox[2] * f.bbox[3]).embedding)
        if not vs:
            continue
        stacked = np.stack(vs)
        kept = filter_enrollment_vectors(stacked, settings.FACE_ENROLLMENT_MIN_CONSISTENCY)
        sims = stacked @ stacked.T
        off = sims[~np.eye(len(vs), dtype=bool)]
        stats[person.name] = {"photos": len(vs), "kept": int(len(kept)),
                              "intra_min": round(float(off.min()), 3) if off.size else None,
                              "intra_mean": round(float(off.mean()), 3) if off.size else None}
        vectors[person.name] = kept
    return vectors, stats


def evaluate(engine, dataset: Path, variant: str) -> dict:
    from backend.app.face_recognition.matching import match_image
    from backend.app.face_recognition.types import Candidate, ImageFaces, MatchCategory
    from backend.app.services.recognition_service import thresholds

    for key, value in VARIANTS[variant].items():
        setattr(settings, key, value)
    labels = json.loads((dataset / "labels.json").read_text(encoding="utf-8"))
    enrolled, enroll_stats = enroll(engine, dataset)
    t = thresholds()
    totals = {k: 0 for k in ("gt_faces", "detected", "roster_faces", "correct_confident", "correct_suggestion",
                             "wrong_confident", "wrong_suggestion", "missed_identity", "unknown_faces",
                             "unknown_kept_unknown", "unknown_false_confident", "unknown_false_suggestion",
                             "extra_detections", "extra_false_confident")}
    genuine, impostor, per_image = [], [], []
    runtime = {"detection_ms": 0.0, "embedding_ms": 0.0, "matching_ms": 0.0}
    for name, spec in labels.items():
        roster = [r for r in spec["roster"] if r in enrolled]
        candidates = [Candidate(student_id=i, vectors=enrolled[r]) for i, r in enumerate(roster)]
        analysis = engine.analyze_classroom(_read(dataset / "images" / name))
        started = time.perf_counter()
        matches = match_image(ImageFaces(image_id=0, faces=analysis.faces), candidates, t) if candidates else []
        runtime["matching_ms"] += (time.perf_counter() - started) * 1000
        runtime["detection_ms"] += analysis.detection.detection_ms
        runtime["embedding_ms"] += analysis.embedding_ms
        used: set[int] = set()
        row = {"image": name, "visible_faces": spec.get("visible_faces"), "gt_faces": len(spec["faces"]),
               "detected": len(analysis.faces), "rotation": analysis.detection.rotation, "tiles": analysis.detection.tiles,
               "merged_duplicates": analysis.detection.merged_duplicates,
               "detection_ms": round(analysis.detection.detection_ms), "recognition_ms": round(analysis.embedding_ms),
               "outcomes": []}
        for gt in spec["faces"]:
            totals["gt_faces"] += 1
            best, best_iou = None, 0.3
            for k, face in enumerate(analysis.faces):
                score = _iou(gt["box"], face.bbox)
                if k not in used and score >= best_iou:
                    best, best_iou = k, score
            label = gt["label"] if gt["label"] in roster else None
            outcome = "not_detected"
            if best is not None:
                used.add(best)
                totals["detected"] += 1
                m = matches[best] if matches else None
                suggested = roster[candidates.index(next(c for c in candidates if c.student_id == m.student_id))] \
                    if m is not None and m.student_id is not None else None
                cat = m.category if m is not None else MatchCategory.NO_MATCH
                if candidates:
                    face_vec = analysis.faces[best].embedding
                    for c, r in zip(candidates, roster):
                        s = float((c.vectors @ face_vec).max())
                        (genuine if r == label else impostor).append(s)
                if label is not None:
                    if cat == MatchCategory.CONFIDENT:
                        outcome = "correct_confident" if suggested == label else "wrong_confident"
                    elif cat in (MatchCategory.LOW_CONFIDENCE, MatchCategory.AMBIGUOUS, MatchCategory.DUPLICATE):
                        outcome = "correct_suggestion" if suggested == label else "wrong_suggestion"
                    else:
                        outcome = "missed_identity"
                else:
                    if cat == MatchCategory.CONFIDENT:
                        outcome = "unknown_false_confident"
                    elif cat in (MatchCategory.LOW_CONFIDENCE, MatchCategory.AMBIGUOUS, MatchCategory.DUPLICATE):
                        outcome = "unknown_false_suggestion"
                    else:
                        outcome = "unknown_kept_unknown"
                row["outcomes"].append({"label": gt["label"], "outcome": outcome, "category": cat.value,
                                        "suggested": suggested, "similarity": None if m is None or m.similarity is None
                                        else round(m.similarity, 3)})
            else:
                row["outcomes"].append({"label": gt["label"], "outcome": outcome})
            if label is not None:
                totals["roster_faces"] += 1
            else:
                totals["unknown_faces"] += 1
            if outcome in totals:
                totals[outcome] += 1
        extras = [k for k in range(len(analysis.faces)) if k not in used]
        totals["extra_detections"] += len(extras)
        totals["extra_false_confident"] += sum(1 for k in extras if matches and matches[k].category == MatchCategory.CONFIDENT)
        per_image.append(row)
    return {"variant": variant, "model": engine.model_name, "thresholds": t.as_dict(), "enrollment": enroll_stats,
            "totals": totals, "runtime_ms": {k: round(v) for k, v in runtime.items()},
            "genuine": sorted(round(s, 3) for s in genuine), "impostor": sorted(round(s, 3) for s in impostor),
            "images": per_image}


def sweep(genuine: list[float], impostor: list[float]) -> list[dict]:
    """For candidate confident thresholds: genuine accepted / impostor accepted."""
    out = []
    for th in (0.35, 0.40, 0.45, 0.50, 0.55, 0.60):
        out.append({"threshold": th, "genuine_accept": sum(s >= th for s in genuine), "genuine": len(genuine),
                    "impostor_accept": sum(s >= th for s in impostor), "impostor": len(impostor)})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--packs", nargs="+", default=[settings.FACE_RECOGNITION_MODEL])
    parser.add_argument("--variants", default="baseline,full")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    from backend.app.face_recognition.model import InsightFaceEngine

    results = []
    for pack in args.packs:
        started = time.perf_counter()
        engine = InsightFaceEngine(pack, Path(settings.FACE_RECOGNITION_MODEL_DIR), settings.FACE_RECOGNITION_DET_SIZE,
                                   allow_download=False)
        load_ms = (time.perf_counter() - started) * 1000
        for variant in args.variants.split(","):
            r = evaluate(engine, args.dataset, variant)
            r["load_ms"] = round(load_ms)
            r["sweep"] = sweep(r["genuine"], r["impostor"])
            results.append(r)
            t = r["totals"]
            print(f"\n== {pack} / {variant}  (load {r['load_ms']} ms)")
            print(f"  detection: {t['detected']}/{t['gt_faces']} labelled faces found, {t['extra_detections']} extra boxes")
            print(f"  roster faces {t['roster_faces']}: confident-correct {t['correct_confident']}, "
                  f"suggested-correct {t['correct_suggestion']}, missed {t['missed_identity']}, "
                  f"WRONG confident {t['wrong_confident']}, wrong suggestion {t['wrong_suggestion']}")
            print(f"  non-roster faces {t['unknown_faces']}: kept unknown {t['unknown_kept_unknown']}, "
                  f"FALSE confident {t['unknown_false_confident'] + t['extra_false_confident']}, "
                  f"false suggestion {t['unknown_false_suggestion']}")
            print(f"  runtime: {r['runtime_ms']}")
            for s in r["sweep"]:
                print(f"  confident>={s['threshold']:.2f}: genuine {s['genuine_accept']}/{s['genuine']}, "
                      f"impostor {s['impostor_accept']}/{s['impostor']}")
    if args.json:
        args.json.write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
