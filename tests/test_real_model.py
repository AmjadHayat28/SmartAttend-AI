"""Opt-in integration tests with the REAL InsightFace models (each pack is skipped if not installed).

Download: uv run python -m backend.app.scripts.download_face_models buffalo_l   (and/or buffalo_sc)

CI does not need these ~300 MB models: lightweight unit tests (test_classroom_detection.py,
test_matching.py, test_recognition*.py) cover the logic with a fake engine. These tests use
InsightFace's own bundled sample group photo (t1.jpg, six adults); they
prove the real pipeline works end to end, not accuracy on any particular population.
"""

from pathlib import Path

import cv2
import numpy as np
import pytest
from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.face_recognition import model as face_model
from backend.app.face_recognition.classroom import iou_matrix
from backend.app.models import (
    FaceEmbedding,
    FaceEnrollmentStatus,
    FaceImageType,
    Student,
    StudentFaceImage,
    TeacherCourseAssignment,
)
from backend.app.services import storage
from backend.app.services.face_embedding_service import ensure_embeddings
from tests import imaging
from tests.conftest import TEACHER_EMAIL
from tests.test_attendance import start

MODEL_DIR = Path(settings.FACE_RECOGNITION_MODEL_DIR)
INSTALLED = [p for p in ("buffalo_l", "buffalo_sc") if (MODEL_DIR / "models" / p / "SHA256SUMS").exists()]
pytestmark = pytest.mark.skipif(not INSTALLED, reason="No InsightFace model pack installed")


def _sample(name: str) -> np.ndarray:
    import insightface

    path = Path(insightface.__file__).parent / "data" / "images" / name
    img = cv2.imread(str(path))
    if img is None:
        pytest.skip(f"InsightFace sample image {name} not available")
    return img


@pytest.fixture(scope="module", params=INSTALLED)
def engine(request):
    return face_model.InsightFaceEngine(request.param, MODEL_DIR, det_size=1024, allow_download=False)


@pytest.fixture()
def real_engine(engine):
    face_model.set_engine(engine)
    yield engine
    face_model.set_engine(None)


def _boxes_xyxy(faces):
    return np.array([[x, y, x + w, y + h] for x, y, w, h in (f.bbox for f in faces)], np.float32)


# ── Model ─────────────────────────────────────────────────────────────────


def test_model_loads(engine):
    assert engine.model_name.startswith("insightface/buffalo_") and engine.dimension == 512
    assert engine.detector_name.startswith("SCRFD det_") and engine.fallback_from is None


def test_one_clear_face_gives_a_unit_embedding(engine):
    t1 = _sample("t1.jpg")
    x, y, w, h = engine.analyze_classroom(t1).faces[0].bbox
    crop = t1[max(0, y - h): y + 2 * h, max(0, x - w): x + 2 * w]
    faces = engine.analyze(crop, purpose="enrollment")
    assert len(faces) == 1
    assert faces[0].embedding.shape == (512,) and abs(float(np.linalg.norm(faces[0].embedding)) - 1) < 1e-3


def test_same_person_scores_higher_than_different_people(engine):
    t1 = _sample("t1.jpg")
    faces = engine.analyze_classroom(t1).faces
    assert len(faces) >= 6
    x, y, w, h = faces[0].bbox
    crop = t1[max(0, y - h): y + 2 * h, max(0, x - w): x + 2 * w]
    variant = cv2.resize(cv2.flip(crop, 1), None, fx=0.8, fy=0.8)  # mirrored + rescaled: same person
    same = float(engine.analyze(variant, purpose="enrollment")[0].embedding @ faces[0].embedding)
    different = max(float(f.embedding @ faces[0].embedding) for f in faces[1:])
    assert same > different + 0.2, (same, different)


def test_group_photo_detects_every_face_once(engine):
    faces = engine.analyze_classroom(_sample("t1.jpg")).faces
    assert len(faces) >= 6
    iou = iou_matrix(_boxes_xyxy(faces), _boxes_xyxy(faces))
    np.fill_diagonal(iou, 0)
    assert iou.max() < 0.3  # no duplicate boxes after merging


def test_small_faces_are_recovered_by_tiles(engine, monkeypatch):
    """t1's six faces shrunk to ~28 px on a 2560×1440 'classroom' (distant students)."""
    t1 = _sample("t1.jpg")
    small = cv2.resize(t1, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    canvas = np.full((1440, 2560, 3), 128, np.uint8)
    canvas[600:600 + small.shape[0], 900:900 + small.shape[1]] = small
    monkeypatch.setattr(settings, "FACE_RECOGNITION_TILING", False)
    full_only = len(engine.analyze_classroom(canvas).faces)
    monkeypatch.setattr(settings, "FACE_RECOGNITION_TILING", True)
    tiled = engine.analyze_classroom(canvas)
    assert len(tiled.faces) >= 5 and len(tiled.faces) >= full_only
    assert tiled.detection.tiles > 1


def test_sideways_photo_is_rotated_and_boxes_stay_on_the_faces(engine):
    t1 = _sample("t1.jpg")
    upright = engine.analyze_classroom(t1).faces
    sideways_img = cv2.rotate(t1, cv2.ROTATE_90_CLOCKWISE)
    sideways = engine.analyze_classroom(sideways_img)
    assert sideways.detection.rotation == 270 and len(sideways.faces) >= len(upright) - 1
    # Every box found on the sideways photo corresponds to an upright face rotated into place.
    h = t1.shape[0]
    expected = np.array([[h - (y + bh), x, h - y, x + bw] for x, y, bw, bh in (f.bbox for f in upright)], np.float32)
    iou = iou_matrix(_boxes_xyxy(sideways.faces), expected)
    assert (iou.max(axis=1) > 0.5).all()


# ── End to end through the API (roster restriction, pre-fill, draft) ──────


def _person_photos(t1: np.ndarray, bbox) -> list[np.ndarray]:
    """Three 'enrollment photos' of one person from the sample group photo: crop, mirror, rescale."""
    x, y, w, h = bbox
    crop = t1[max(0, y - h): y + 2 * h, max(0, x - w): x + 2 * w]
    return [cv2.resize(crop, (480, 560)), cv2.resize(cv2.flip(crop, 1), (480, 560)),
            cv2.resize(crop, (400, 470))]


def _enroll(db, student_id: int, photos: list[np.ndarray]):
    student = db.get(Student, student_id)
    for pose, img in zip([FaceImageType.FRONT, FaceImageType.LEFT, FaceImageType.RIGHT], photos):
        path = storage.save("faces", student_id, imaging.jpeg(img))
        db.add(StudentFaceImage(student_id=student_id, image_path=path, image_type=pose, width=img.shape[1],
                                height=img.shape[0], file_size=1))
    student.face_enrollment_status = FaceEnrollmentStatus.APPROVED


def test_real_pipeline_end_to_end(client, login, hod_h, ids, db_session, real_engine):
    teacher_h = login(TEACHER_EMAIL)
    other = client.post("/api/v1/students", headers=hod_h, json={
        "full_name": "Persona C", "email": "pc@test.edu", "password": "Student@123", "registration_no": "F23CSE40",
        "batch_id": ids["batch"], "semester_id": ids["semester"], "section_id": ids["section_a"]}).json()
    with db_session() as db:
        assignment = db.scalar(select(TeacherCourseAssignment.id).where(
            TeacherCourseAssignment.course_id == ids["courses"]["CS-321"]))
    client.post("/api/v1/enrollments", headers=teacher_h, json={"assignment_id": assignment, "student_id": other["id"]})
    # Two people of the sample group photo are enrolled; the other four are strangers.
    t1 = _sample("t1.jpg")
    people = real_engine.analyze_classroom(t1).faces
    assert len(people) >= 6
    with db_session() as db:
        _enroll(db, ids["student"], _person_photos(t1, people[0].bbox))
        _enroll(db, other["id"], _person_photos(t1, people[1].bbox))
        db.commit()
        reports = ensure_embeddings(db, [ids["student"], other["id"]], real_engine)
        db.commit()
        assert all(r.ok and r.created == 3 for r in reports), [r.failed for r in reports]
        vec = np.frombuffer(db.scalar(select(FaceEmbedding.embedding_vector)), dtype=np.float32)
        assert vec.shape == (512,) and abs(np.linalg.norm(vec) - 1) < 1e-3

    session = start(client, teacher_h, assignment).json()["session"]
    up = client.post(f"/api/v1/attendance/sessions/{session['id']}/images", headers=teacher_h,
                     files={"file": ("c.jpg", imaging.jpeg(t1), "image/jpeg")})
    assert up.status_code == 201
    res = client.post(f"/api/v1/attendance/sessions/{session['id']}/recognition", headers=teacher_h,
                      json={"version": up.json()["version"]})
    assert res.status_code == 200, res.text
    body = res.json()
    run = body["recognition"]["run"]
    assert run["model_name"] == real_engine.model_name and run["diagnostics"]["model"] == real_engine.model_name
    assert run["faces_detected"] >= 6
    # The four strangers are never confidently matched to a roster student (roster restriction).
    confident = [f for f in body["recognition"]["faces"] if f["category"] == "confident"]
    assert sorted(f["suggested"]["registration_no"] for f in confident) == ["F23CSE01", "F23CSE40"]
    matched = {f["assigned"]["registration_no"] for f in body["recognition"]["faces"] if f["assigned"]}
    assert matched == {"F23CSE01", "F23CSE40"}, body["recognition"]["faces"]
    statuses = {r["registration_no"]: (r["status"], r["method"]) for r in body["session"]["records"]}
    assert statuses["F23CSE01"] == ("present", "face_recognition")
    assert statuses["F23CSE40"] == ("present", "face_recognition")
    assert body["session"]["status"] == "draft"
