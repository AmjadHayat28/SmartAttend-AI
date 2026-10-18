"""Explicit, testable matching of classroom faces to *session-roster* candidates.

Algorithm
1. Similarity: cosine similarity between unit vectors (= dot product). A student may have
   several approved embeddings (front/left/right/extra); a face's score for a student is the
   **best** (max) over that student's embeddings.
2. Per photo, one-to-one assignment: all (face, student) pairs at or above the low threshold
   are taken greedily from the highest score down; a face gets at most one student and a
   student at most one face *within that photo*.
3. Category of each face (from its assigned student's score s, and its best score s2 for any
   *other* student not already matched to another face in the photo):
       s >= confident and s - s2 >= margin   → CONFIDENT
       s >= low       and s - s2 <  margin   → AMBIGUOUS   (teacher chooses)
       s >= low                              → LOW_CONFIDENCE (teacher accepts/rejects)
       a face whose best student was taken by a stronger face in the same photo
                                             → DUPLICATE (suggestion kept for review)
       otherwise                             → NO_MATCH
4. Across photos the same student can legitimately appear more than once. Every sighting
   is kept, but only the strongest one is marked `is_primary`; attendance is applied once.
"""

from __future__ import annotations

import numpy as np

from backend.app.face_recognition.types import Candidate, FaceMatch, ImageFaces, MatchCategory, Thresholds


def filter_enrollment_vectors(vectors: np.ndarray, min_consistency: float) -> np.ndarray:
    """Drop enrollment embeddings that do not resemble the student's other photos.

    Best-of-N matching means one bad embedding (wrong person, blurred, a poster in the
    background) could attract other people's faces. With ≥3 photos, an embedding whose mean
    cosine similarity to the student's other embeddings is below `min_consistency` is left out.
    With fewer photos there is no majority to compare against, so nothing is dropped; if every
    photo would be dropped the student keeps all of them (the HOD approved them).
    """
    if len(vectors) < 3 or min_consistency <= -1:
        return vectors
    sims = vectors @ vectors.T
    mean_other = (sims.sum(axis=1) - np.diag(sims)) / (len(vectors) - 1)
    keep = mean_other >= min_consistency
    return vectors[keep] if keep.any() else vectors


def student_scores(face_vectors: np.ndarray, candidates: list[Candidate]) -> np.ndarray:
    """(faces × students) matrix of best cosine similarity per student. Vectorised."""
    if not candidates or face_vectors.size == 0:
        return np.zeros((len(face_vectors), len(candidates)), dtype=np.float32)
    stacked = np.concatenate([c.vectors for c in candidates], axis=0)  # (total_k, dim)
    owners = np.concatenate([np.full(len(c.vectors), i) for i, c in enumerate(candidates)])
    sims = face_vectors @ stacked.T  # (faces, total_k)
    scores = np.full((len(face_vectors), len(candidates)), -1.0, dtype=np.float32)
    np.maximum.at(scores.T, owners, sims.T)  # per-student max over their embeddings
    return scores


def _second_best(row: np.ndarray, exclude: set[int]) -> tuple[int | None, float | None]:
    """Best remaining candidate, ignoring `exclude` (the face's own student and students
    already matched to other faces in the photo — those are not real rivals)."""
    masked = row.astype(np.float64).copy()
    for j in exclude:
        masked[j] = -np.inf
    if not np.isfinite(masked).any():
        return None, None
    j = int(np.argmax(masked))
    return j, float(masked[j])


def match_image(image: ImageFaces, candidates: list[Candidate], t: Thresholds) -> list[FaceMatch]:
    faces = image.faces
    results = [FaceMatch(image_id=image.image_id, face_index=i, bbox=f.bbox, det_score=f.det_score,
                         category=MatchCategory.NO_MATCH) for i, f in enumerate(faces)]
    if not faces or not candidates:
        return results
    scores = student_scores(np.stack([f.embedding for f in faces]), candidates)

    # Greedy one-to-one assignment, strongest pairs first.
    pairs = [(float(scores[i, j]), i, j) for i in range(len(faces)) for j in range(len(candidates))
             if scores[i, j] >= t.low]
    pairs.sort(reverse=True)
    face_taken: dict[int, int] = {}
    student_taken: set[int] = set()
    for score, i, j in pairs:
        if i in face_taken or j in student_taken:
            continue
        face_taken[i] = j
        student_taken.add(j)

    for i, result in enumerate(results):
        row = scores[i]
        if i in face_taken:
            j = face_taken[i]
            s = float(row[j])
            others = {jj for ii, jj in face_taken.items() if ii != i}
            k, s2 = _second_best(row, {j} | others)
            result.student_id, result.similarity = candidates[j].student_id, s
            if k is not None:
                result.second_student_id, result.second_similarity = candidates[k].student_id, s2
            close = s2 is not None and s2 >= t.low and (s - s2) < t.margin
            if close:
                result.category = MatchCategory.AMBIGUOUS
            elif s >= t.confident:
                result.category = MatchCategory.CONFIDENT
            else:
                result.category = MatchCategory.LOW_CONFIDENCE
        else:
            best = int(np.argmax(row))
            if float(row[best]) >= t.low:
                # Its best student went to a stronger face in this same photo.
                result.category = MatchCategory.DUPLICATE
                result.student_id, result.similarity = candidates[best].student_id, float(row[best])
            else:
                result.similarity = float(row[best]) if row.size else None
    return results


def match_session(images: list[ImageFaces], candidates: list[Candidate], t: Thresholds) -> list[FaceMatch]:
    """Match every photo, then keep one primary sighting per student across photos."""
    all_results = [r for image in images for r in match_image(image, candidates, t)]
    best: dict[int, FaceMatch] = {}
    rank = {MatchCategory.CONFIDENT: 0, MatchCategory.LOW_CONFIDENCE: 1, MatchCategory.AMBIGUOUS: 2,
            MatchCategory.DUPLICATE: 3, MatchCategory.NO_MATCH: 4}
    for r in all_results:
        if r.student_id is None or r.category in (MatchCategory.DUPLICATE, MatchCategory.NO_MATCH):
            continue
        current = best.get(r.student_id)
        key = (rank[r.category], -(r.similarity or 0.0))
        if current is None or key < (rank[current.category], -(current.similarity or 0.0)):
            best[r.student_id] = r
    for r in all_results:
        if r.student_id is not None and r.category not in (MatchCategory.DUPLICATE, MatchCategory.NO_MATCH):
            r.is_primary = best.get(r.student_id) is r
    return all_results
