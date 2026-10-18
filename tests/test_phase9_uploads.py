"""Phase 9: classroom-photo upload safety, tested through the real upload endpoint.

Formats, malformed/corrupt files, file-size limits (incl. chunked uploads without a
Content-Length), pixel/dimension limits checked from the header, aspect ratio, and that normal
phone photos are accepted without being altered beyond the documented storage size.
"""

import io
import struct
import zlib

import cv2
import numpy as np
import pytest
from PIL import Image

from backend.app.core.config import settings
from tests import imaging
from tests.test_attendance import cls, start, teacher_h  # noqa: F401  (fixtures)

API = "/api/v1"


def _scene(width: int, height: int) -> np.ndarray:
    return cv2.resize(imaging.no_face(), (width, height))


def _post(client, headers, session_id, data: bytes, content_type: str, name: str = "c.jpg"):
    return client.post(f"{API}/attendance/sessions/{session_id}/images", headers=headers,
                       files={"file": (name, data, content_type)})


@pytest.fixture()
def draft(client, teacher_h, cls):  # noqa: F811
    return start(client, teacher_h, cls["assignment"]).json()["session"]


def _png_header_only(width: int, height: int) -> bytes:
    """A PNG whose header claims width×height but carries almost no pixel data (bomb shape)."""
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00" * 64)) + chunk(b"IEND", b"")


# ── Formats and malformed files ───────────────────────────────────────────


@pytest.mark.parametrize("content_type,data", [
    ("image/gif", imaging.gif_bytes()),
    ("image/webp", b"RIFF\x00\x00\x00\x00WEBPVP8 "),
    ("image/heic", b"\x00\x00\x00\x18ftypheic"),
    ("application/pdf", b"%PDF-1.4\n"),
], ids=["gif", "webp", "heic", "pdf"])
def test_unsupported_formats_are_refused(client, teacher_h, draft, content_type, data):
    res = _post(client, teacher_h, draft["id"], data, content_type)
    assert res.status_code == 415 and "JPEG or PNG" in res.json()["detail"]


def test_declared_type_must_match_the_content(client, teacher_h, draft):
    res = _post(client, teacher_h, draft["id"], imaging.png(_scene(800, 600)), "image/jpeg")
    assert res.status_code == 415 and "does not match" in res.json()["detail"]
    gif_as_png = _post(client, teacher_h, draft["id"], imaging.gif_bytes(), "image/png")
    assert gif_as_png.status_code == 415


@pytest.mark.parametrize("data", [
    b"",
    b"\xff\xd8\xff\xe0 not really a jpeg",
    imaging.jpeg(_scene(800, 600))[:4000],  # truncated mid-image
    bytes(np.random.default_rng(1).integers(0, 255, 50_000, dtype=np.uint8)),
], ids=["empty", "fake-jpeg-header", "truncated-jpeg", "random-bytes"])
def test_corrupt_or_empty_files_are_refused_with_a_friendly_message(client, teacher_h, draft, data):
    res = _post(client, teacher_h, draft["id"], data, "image/jpeg")
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert "empty" in detail or "corrupt or unreadable" in detail
    assert "Traceback" not in res.text and "PIL" not in res.text


# ── File size ─────────────────────────────────────────────────────────────


def test_oversized_file_is_refused(client, teacher_h, draft, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0.05)  # 51 KB
    big = imaging.jpeg(_scene(1600, 1200), quality=98)
    assert len(big) > 0.05 * 1024 * 1024
    res = _post(client, teacher_h, draft["id"], big, "image/jpeg")
    assert res.status_code == 413 and "too large" in res.json()["detail"]


def test_oversized_content_length_is_refused_before_reading(client, teacher_h, draft):
    res = client.post(f"{API}/attendance/sessions/{draft['id']}/images", content=b"x",
                      headers={**teacher_h, "content-type": "multipart/form-data; boundary=b",
                               "content-length": str(500 * 1024 * 1024)})
    assert res.status_code == 413 and "too large" in res.json()["detail"]


def test_chunked_upload_without_content_length_is_refused(client, teacher_h, draft, monkeypatch, isolated_uploads):
    """No Content-Length (chunked transfer): the body is counted as it arrives → 413, nothing stored."""
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0.25)

    def body():
        yield (b"--b\r\nContent-Disposition: form-data; name=\"file\"; filename=\"c.jpg\"\r\n"
               b"Content-Type: image/jpeg\r\n\r\n")
        for _ in range(64):  # 64 × 64 KB = 4 MB, far over the limit
            yield b"\xff" * 65536
        yield b"\r\n--b--\r\n"

    res = client.post(f"{API}/attendance/sessions/{draft['id']}/images", content=body(),
                      headers={**teacher_h, "content-type": "multipart/form-data; boundary=b"})
    assert res.status_code == 413 and "too large" in res.json()["detail"]
    assert client.get(f"{API}/attendance/sessions/{draft['id']}", headers=teacher_h).json()["images"] == []
    assert not list(isolated_uploads.rglob("*.jpg"))


def test_size_limit_stops_consuming_a_stream_once_over_the_limit(monkeypatch):
    """ASGI level: chunks after the limit are never pulled from the client."""
    import anyio
    from fastapi import HTTPException

    from backend.app.main import UploadSizeLimit

    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0.25)  # 256 KB + 64 KB framing allowance
    pulled = []

    async def receive():
        pulled.append(1)
        return {"type": "http.request", "body": b"\x00" * 65536, "more_body": True}  # endless 64 KB chunks

    async def inner(scope, receive_, send):
        while True:
            await receive_()

    async def send(message):  # pragma: no cover - nothing is sent
        raise AssertionError(message)

    scope = {"type": "http", "headers": [(b"content-type", b"multipart/form-data; boundary=b")]}
    with pytest.raises(HTTPException) as err:
        anyio.run(UploadSizeLimit(inner), scope, receive, send)
    assert err.value.status_code == 413 and len(pulled) == 6  # 6 × 64 KB = 384 KB > 320 KB


# ── Dimensions ────────────────────────────────────────────────────────────


def test_pixel_bomb_is_refused_from_the_header_without_decoding(client, teacher_h, draft):
    data = _png_header_only(20_000, 20_000)  # 400 MP claimed in ~100 bytes
    assert len(data) < 200
    res = _post(client, teacher_h, draft["id"], data, "image/png")
    assert res.status_code == 422 and "dimensions are too large" in res.json()["detail"]
    moderate = _post(client, teacher_h, draft["id"], _png_header_only(9000, 6000), "image/png")  # 54 MP
    assert moderate.status_code == 422 and "9000×6000" in moderate.json()["detail"]


def test_too_many_pixels(client, teacher_h, draft, monkeypatch):
    monkeypatch.setattr(settings, "IMAGE_MAX_PIXELS", 1_000_000)
    res = _post(client, teacher_h, draft["id"], imaging.jpeg(_scene(1600, 1200)), "image/jpeg")
    assert res.status_code == 422 and "megapixels" in res.json()["detail"]


def test_too_small(client, teacher_h, draft):
    res = _post(client, teacher_h, draft["id"], imaging.jpeg(_scene(640, 400)), "image/jpeg")
    assert res.status_code == 422 and "too small" in res.json()["detail"]


def test_unreasonable_aspect_ratio_is_refused_but_panoramas_are_fine(client, teacher_h, draft):
    strip = _post(client, teacher_h, draft["id"], imaging.jpeg(_scene(3100, 500)), "image/jpeg")  # 6.2 : 1
    assert strip.status_code == 422 and "long and narrow" in strip.json()["detail"]
    panorama = _post(client, teacher_h, draft["id"], imaging.jpeg(_scene(2500, 500)), "image/jpeg")  # 5 : 1
    assert panorama.status_code == 201, panorama.text


# ── Normal phone photos are kept as they are ──────────────────────────────


def test_normal_phone_photo_keeps_its_resolution(client, teacher_h, draft, isolated_uploads):
    res = _post(client, teacher_h, draft["id"], imaging.jpeg(_scene(1920, 1080)), "image/jpeg")
    assert res.status_code == 201, res.text
    [image] = res.json()["images"]
    assert (image["width"], image["height"]) == (1920, 1080)  # at or under 2560: never resized
    [stored] = list(isolated_uploads.rglob("*.jpg"))
    assert Image.open(stored).size == (1920, 1080)


def test_12mp_phone_photo_is_stored_at_the_documented_size_with_its_aspect(client, teacher_h, draft):
    res = _post(client, teacher_h, draft["id"], imaging.jpeg(_scene(4032, 3024), quality=85), "image/jpeg")
    assert res.status_code == 201, res.text
    [image] = res.json()["images"]
    assert (image["width"], image["height"]) == (settings.ATTENDANCE_PHOTO_MAX_DIMENSION, 1920)


def test_exif_rotated_phone_photo_is_stored_upright(client, teacher_h, draft):
    img = Image.fromarray(cv2.cvtColor(_scene(1600, 1200), cv2.COLOR_BGR2RGB))
    exif = img.getexif()
    exif[0x0112] = 6  # "rotate 90° CW to display" — how phones store portrait shots
    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif, quality=90)
    res = _post(client, teacher_h, draft["id"], out.getvalue(), "image/jpeg")
    assert res.status_code == 201, res.text
    [image] = res.json()["images"]
    assert (image["width"], image["height"]) == (1200, 1600)


def test_png_classroom_photo_is_accepted(client, teacher_h, draft):
    res = _post(client, teacher_h, draft["id"], imaging.png(_scene(1280, 960)), "image/png", "c.png")
    assert res.status_code == 201, res.text
