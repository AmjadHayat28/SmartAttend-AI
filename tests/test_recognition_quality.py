"""Phase 8: model selection/fallback, run diagnostics, and enrollment-embedding quality."""

import json

import numpy as np
import pytest
from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.face_recognition import model as face_model
from backend.app.face_recognition.matching import filter_enrollment_vectors
from backend.app.models import AuditLog, FaceEmbedding, FaceImageType, StudentFaceImage
from tests.fake_face_engine import random_identity, with_similarity
from tests.test_recognition import classroom_photo, give_profile, rc, rec_of, run, teacher_h  # noqa: F401

API = "/api/v1"


# ── Model selection ───────────────────────────────────────────────────────


class _Engine:
    def __init__(self, name):
        self.model_name = f"insightface/{name}"
        self.model_version, self.dimension, self.detector_name = "test", 512, "SCRFD test"
        self.fallback_from = None


def test_configured_model_is_preferred():
    loaded = []

    def loader(name):
        loaded.append(name)
        return _Engine(name)

    engine = face_model.load_engine("buffalo_l", "buffalo_sc", loader)
    assert engine.model_name == "insightface/buffalo_l" and engine.fallback_from is None and loaded == ["buffalo_l"]


def test_controlled_fallback_is_recorded():
    def loader(name):
        if name == "buffalo_l":
            raise face_model.FaceModelUnavailable("not installed")
        return _Engine(name)

    engine = face_model.load_engine("buffalo_l", "buffalo_sc", loader)
    assert engine.model_name == "insightface/buffalo_sc" and engine.fallback_from == "buffalo_l"


@pytest.mark.parametrize("fallback", [None, "", "buffalo_l"])
def test_no_fallback_configured_raises(fallback):
    def loader(name):
        raise face_model.FaceModelUnavailable("not installed")

    with pytest.raises(face_model.FaceModelUnavailable):
        face_model.load_engine("buffalo_l", fallback or None, loader)


def test_engine_is_loaded_once_and_reused(monkeypatch):
    calls = []
    monkeypatch.setattr(face_model, "_load", lambda name: calls.append(name) or _Engine(name))
    monkeypatch.setattr(settings, "FACE_RECOGNITION_MODEL", "buffalo_l")
    face_model.set_engine(None)
    try:
        first, second = face_model.get_engine(), face_model.get_engine()
        assert first is second and calls == ["buffalo_l"]
    finally:
        face_model.set_engine(None)


# ── Run diagnostics ───────────────────────────────────────────────────────


def test_run_records_model_and_non_sensitive_diagnostics(client, teacher_h, rc, fake_face_engine):
    s, v = rc["session"], rc["vec"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600,
                    [with_similarity(v["F23CSE01"], 0.8, 1), random_identity(555)])
    body = run(client, teacher_h, s).json()
    d = body["recognition"]["run"]["diagnostics"]
    assert d["model"] == fake_face_engine.model_name == body["recognition"]["run"]["model_name"]
    assert d["fallback_from"] is None and d["configured_model"] == settings.FACE_RECOGNITION_MODEL
    assert {"detection_ms", "recognition_ms", "matching_ms", "total_ms", "detector", "settings"} <= set(d)
    assert d["images"][0]["faces"] == 2 and d["images"][0]["image_id"] == body["recognition"]["faces"][0]["image_id"]
    assert not any("fallback" in w for w in body["recognition"]["run"]["warnings"])
    text = json.dumps(d).lower()
    assert "embedding" not in text and "vector" not in text and "uploads" not in text and ".jpg" not in text


def test_fallback_model_is_visible_on_the_run(client, teacher_h, rc, fake_face_engine, db_session):
    fake_face_engine.fallback_from = "buffalo_l"
    s, v = rc["session"], rc["vec"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [with_similarity(v["F23CSE01"], 0.8, 1)])
    r = run(client, teacher_h, s).json()["recognition"]["run"]
    assert r["status"] == "completed_with_warnings"
    assert any("'buffalo_l' is unavailable" in w for w in r["warnings"])
    assert r["diagnostics"]["fallback_from"] == "buffalo_l" and r["diagnostics"]["model"] == fake_face_engine.model_name
    with db_session() as db:
        done = db.scalar(select(AuditLog).where(AuditLog.action == "recognition.run_completed"))
        assert done.new_value["fallback_from"] == "buffalo_l"


# ── Enrollment embedding quality ──────────────────────────────────────────


def test_filter_drops_an_inconsistent_enrollment_photo():
    me = random_identity(1)
    other = random_identity(2)
    vectors = np.stack([me, with_similarity(me, 0.7, 1), with_similarity(me, 0.65, 2), other])
    kept = filter_enrollment_vectors(vectors, 0.2)
    assert len(kept) == 3 and not any(np.allclose(k, other) for k in kept)


def test_filter_needs_a_majority_and_never_empties_a_profile():
    a, b = random_identity(1), random_identity(2)
    assert len(filter_enrollment_vectors(np.stack([a, b]), 0.2)) == 2  # two photos: nothing to compare
    unrelated = np.stack([random_identity(i) for i in range(3)])
    assert len(filter_enrollment_vectors(unrelated, 0.2)) == 3  # all inconsistent: keep (HOD approved)


def test_wrong_person_in_enrollment_photos_cannot_cause_a_confident_match(client, teacher_h, rc, fake_face_engine,
                                                                           db_session):
    """F23CSE04's profile gets an extra photo that is really someone else (the outsider). Without
    the consistency filter, the outsider's face would match F23CSE04 at 1.0 → wrongly Present."""
    sid, v = rc["sid"], rc["vec"]
    with db_session() as db:
        image = StudentFaceImage(student_id=sid["F23CSE04"], image_path=f"faces/{sid['F23CSE04']}/{'%032x' % 99}.jpg",
                                 image_type=FaceImageType.EXTRA, width=640, height=640, file_size=1)
        db.add(image)
        db.flush()
        db.refresh(image)
        db.add(FaceEmbedding(student_id=sid["F23CSE04"], face_image_id=image.id, embedding_vector=v["OUT"].tobytes(),
                             dimension=v["OUT"].shape[0], model_name=fake_face_engine.model_name,
                             model_version=fake_face_engine.model_version, source_updated_at=image.updated_at))
        db.commit()
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600, [v["OUT"]])  # only the outsider is there
    body = run(client, teacher_h, s).json()
    face = body["recognition"]["faces"][0]
    assert face["category"] == "no_match" and face["suggested"] is None
    assert rec_of(body["session"], "F23CSE04")["status"] is None
