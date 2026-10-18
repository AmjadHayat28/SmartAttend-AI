"""Unit tests for upload validation (synthetic images only)."""

import io

import pytest
from PIL import Image

from backend.app.core.config import settings
from backend.app.face_recognition import detection
from backend.app.face_recognition.detection import DetectedFace
from backend.app.services import image_validation, storage
from backend.app.services.image_validation import ImageRejected, validate_face_photo, validate_profile_photo
from tests import imaging


def _rejected(data: bytes, content_type: str = "image/png") -> ImageRejected:
    with pytest.raises(ImageRejected) as exc:
        validate_face_photo(data, content_type)
    return exc.value


# ── Accepted images ───────────────────────────────────────────────────────


@pytest.mark.parametrize("turn", [0, -30, 30])
def test_single_face_passes_and_is_reencoded(turn):
    result = validate_face_photo(imaging.png(imaging.face(turn=turn)), "image/png")
    assert result.status.value == "pass" and result.message is None
    assert result.jpeg[:2] == b"\xff\xd8"  # stored as a fresh JPEG regardless of input format
    assert result.face["score"] >= settings.FACE_DETECTION_SCORE
    assert {c["check"] for c in result.checks} == {"resolution", "face_size", "blur", "brightness"}


def test_jpeg_input_accepted():
    assert validate_face_photo(imaging.jpeg(imaging.face()), "image/jpeg").width == 640


def test_low_resolution_is_a_warning_not_a_failure():
    result = validate_face_photo(imaging.png(imaging.face(320)), "image/png")
    assert result.status.value == "warning" and "Low resolution" in result.message


def test_large_images_are_downscaled_for_storage():
    import cv2

    big = cv2.resize(imaging.face(), (2400, 2400))
    result = validate_face_photo(imaging.jpeg(big), "image/jpeg")
    assert max(result.width, result.height) == settings.IMAGE_STORE_MAX_DIMENSION


def test_metadata_is_stripped():
    img = Image.fromarray(imaging.face()[:, :, ::-1])
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"  # Make
    exif[0x8825] = {2: (51.0, 30.0, 0.0)}  # GPS latitude
    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif)
    assert b"SecretCameraMaker" in out.getvalue()
    stored = validate_face_photo(out.getvalue(), "image/jpeg").jpeg
    assert b"SecretCameraMaker" not in stored and not Image.open(io.BytesIO(stored)).getexif()


# ── Rejected images ───────────────────────────────────────────────────────


def test_no_face():
    assert _rejected(imaging.png(imaging.no_face())).message == "No face detected. Please upload a clearer photo."


def test_multiple_faces():
    assert _rejected(imaging.png(imaging.two_faces())).message.startswith("Multiple faces detected")


def test_blank_image():
    assert "blank" in _rejected(imaging.png(imaging.blank())).message


def test_blurry_face():
    assert "blurry" in _rejected(imaging.png(imaging.blurred())).message


def test_too_small():
    err = _rejected(imaging.png(imaging.face(150)))
    assert err.message.startswith("Image is too small") and err.status_code == 422


def test_corrupt_and_truncated():
    assert "corrupt" in _rejected(b"\xff\xd8\xff\xe0 not really a jpeg", "image/jpeg").message
    full = imaging.jpeg(imaging.face())
    assert "corrupt" in _rejected(full[: len(full) // 3], "image/jpeg").message


def test_unsupported_types():
    assert _rejected(imaging.gif_bytes(), "image/gif").status_code == 415
    assert _rejected(imaging.png(imaging.face()), "image/webp").status_code == 415
    assert _rejected(b"hello", "text/plain").status_code == 415


def test_extension_and_declared_type_are_not_trusted():
    # PNG bytes declared as JPEG, and a GIF disguised as PNG, are both refused.
    assert "does not match" in _rejected(imaging.png(imaging.face()), "image/jpeg").message
    assert _rejected(imaging.gif_bytes(), "image/png").status_code == 415


def test_oversized(monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0.01)
    err = _rejected(imaging.png(imaging.face()))
    assert err.status_code == 413 and "too large" in err.message


def test_empty_file():
    assert _rejected(b"").message == "The file is empty."


# ── Brightness thresholds (detector stubbed: the real one rarely finds faces this dark) ──


@pytest.fixture()
def stub_face(monkeypatch):
    monkeypatch.setattr(image_validation, "detect_faces",
                        lambda img, threshold: [DetectedFace(x=160, y=160, width=320, height=320, score=0.9)])


def _uniform_face_image(level: int):
    img = imaging.face()
    img[160:480, 160:480] = (img[160:480, 160:480].astype(int) * 0 + level + (img[160:480, 160:480] % 40)).clip(0, 255)
    return img


def test_too_dark_fails(stub_face):
    assert "too dark" in _rejected(imaging.png(_uniform_face_image(5))).message


def test_overexposed_fails(stub_face):
    assert "overexposed" in _rejected(imaging.png(_uniform_face_image(225))).message


def test_dim_lighting_warns(stub_face):
    result = validate_face_photo(imaging.png(_uniform_face_image(40)), "image/png")
    assert result.status.value == "warning" and "dark" in result.message


# ── Profile photos ────────────────────────────────────────────────────────


def test_profile_photo_does_not_require_a_face():
    result = validate_profile_photo(imaging.png(imaging.no_face()), "image/png")
    assert result.jpeg[:2] == b"\xff\xd8"
    with pytest.raises(ImageRejected):
        validate_profile_photo(imaging.png(imaging.face(120)), "image/png")


# ── Detector integrity and storage safety ─────────────────────────────────


def test_detector_refuses_tampered_model(monkeypatch):
    detection._detector.cache_clear()
    monkeypatch.setattr(detection, "MODEL_SHA256", "0" * 64)
    with pytest.raises(detection.FaceDetectorUnavailable):
        detection.detect_faces(imaging.face(), 0.7)
    detection._detector.cache_clear()


@pytest.mark.parametrize("bad", ["../secret.txt", "faces/../../x.jpg", "/etc/passwd", "C:/Windows/win.ini", "",
                                 "faces\1\\" + "a" * 32 + ".jpg", "faces/1/" + "a" * 32 + ".jpg/../../x",
                                 "faces/0/" + "a" * 32 + ".jpg", "other/1/" + "a" * 32 + ".jpg"])
def test_storage_rejects_path_traversal(bad):
    with pytest.raises(storage.StorageError):
        storage.resolve(bad)


def test_storage_uses_random_names(isolated_uploads):
    a = storage.save("faces", 5, b"x")
    b = storage.save("faces", 5, b"y")
    assert a != b and a.startswith("faces/5/") and a.endswith(".jpg") and len(a.split("/")[-1]) == 36
    assert storage.resolve(a).is_relative_to(isolated_uploads.resolve())
    assert (isolated_uploads / a).read_bytes() == b"x"
