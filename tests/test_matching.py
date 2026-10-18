"""Unit tests for the matching algorithm — synthetic vectors only."""

import numpy as np
import pytest

from backend.app.face_recognition.matching import match_image, match_session, student_scores
from backend.app.face_recognition.types import Candidate, FaceObservation, ImageFaces, MatchCategory, Thresholds
from tests.fake_face_engine import blend, random_identity, with_similarity

T = Thresholds(confident=0.50, low=0.35, margin=0.06)
A, B, C = random_identity(1), random_identity(2), random_identity(3)


def cand(sid, *vectors):
    return Candidate(student_id=sid, vectors=np.stack(vectors))


def photo(image_id, *embeddings):
    return ImageFaces(image_id=image_id, faces=[FaceObservation(bbox=(i * 50, 0, 40, 40), det_score=0.9, embedding=e)
                                                for i, e in enumerate(embeddings)])


ROSTER = [cand(1, A), cand(2, B), cand(3, C)]


def test_best_score_over_a_students_embeddings():
    front, side = with_similarity(A, 0.95, 1), with_similarity(A, 0.6, 2)
    face = with_similarity(side, 0.9, 3)  # resembles the side-view photo most
    scores = student_scores(np.stack([face]), [cand(1, front, side)])
    assert scores[0, 0] == pytest.approx(float(face @ side), abs=1e-5)


@pytest.mark.parametrize("sim,category", [(0.8, MatchCategory.CONFIDENT), (0.42, MatchCategory.LOW_CONFIDENCE),
                                          (0.2, MatchCategory.NO_MATCH)])
def test_categories(sim, category):
    [r] = match_image(photo(1, with_similarity(A, sim)), ROSTER, T)
    assert r.category == category
    if category != MatchCategory.NO_MATCH:
        assert r.student_id == 1 and r.similarity == pytest.approx(sim, abs=1e-4)
    else:
        assert r.student_id is None


def test_ambiguous_when_two_candidates_are_too_close():
    [r] = match_image(photo(1, blend([(A, 0.62), (B, 0.59)])), ROSTER, T)
    assert r.category == MatchCategory.AMBIGUOUS and r.student_id == 1 and r.second_student_id == 2
    assert r.second_similarity == pytest.approx(0.59, abs=1e-3)


def test_clear_margin_is_not_ambiguous():
    [r] = match_image(photo(1, blend([(A, 0.70), (B, 0.40)])), ROSTER, T)
    assert r.category == MatchCategory.CONFIDENT


def test_lookalike_already_matched_elsewhere_is_not_a_rival():
    # Face 1 is A (close to B); face 2 is clearly B. Face 1 must not be "ambiguous" because B
    # already belongs to face 2.
    rs = match_image(photo(1, blend([(A, 0.62), (B, 0.59)]), with_similarity(B, 0.9)), ROSTER, T)
    assert [(r.student_id, r.category) for r in rs] == [(1, MatchCategory.CONFIDENT), (2, MatchCategory.CONFIDENT)]


def test_one_to_one_duplicate_within_a_photo():
    rs = match_image(photo(1, with_similarity(A, 0.7, 1), with_similarity(A, 0.9, 2)), ROSTER, T)
    assert rs[1].category == MatchCategory.CONFIDENT and rs[1].student_id == 1
    assert rs[0].category == MatchCategory.DUPLICATE and rs[0].student_id == 1


def test_same_student_in_two_photos_has_one_primary_sighting():
    rs = match_session([photo(1, with_similarity(A, 0.7)), photo(2, with_similarity(A, 0.9))], ROSTER, T)
    assert all(r.category == MatchCategory.CONFIDENT and r.student_id == 1 for r in rs)
    assert [r.is_primary for r in rs] == [False, True]


def test_only_candidates_can_ever_match():
    outsider = random_identity(99)
    [r] = match_image(photo(1, with_similarity(outsider, 0.99)), ROSTER, T)
    assert r.category == MatchCategory.NO_MATCH  # the outsider is not a candidate, so no suggestion


def test_no_candidates_or_no_faces():
    assert match_image(photo(1, A), [], T)[0].category == MatchCategory.NO_MATCH
    assert match_image(photo(1), ROSTER, T) == []
