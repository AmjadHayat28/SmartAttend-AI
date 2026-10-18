"""Model download/integrity checks — offline (no network, no real model)."""

import hashlib
import zipfile

import pytest

from backend.app.face_recognition import model_store
from backend.app.face_recognition.model import FaceModelUnavailable, InsightFaceEngine
from backend.app.face_recognition.model_store import ModelDownloadError, install_pack, record_checksums, verify_installed


def _pack(tmp_path, name="testpack", files=None):
    files = files or {"det.onnx": b"detector-bytes", "rec.onnx": b"recognizer-bytes"}
    zip_path = tmp_path / "models" / f"{name}.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as zf:
        for fname, data in files.items():
            zf.writestr(fname, data)
    return zip_path, hashlib.sha256(zip_path.read_bytes()).hexdigest()


def test_install_verifies_pinned_digest_and_records_checksums(tmp_path, monkeypatch):
    zip_path, digest = _pack(tmp_path)
    monkeypatch.setitem(model_store.KNOWN_PACKS, "testpack", (digest, 0.1))
    target = install_pack("testpack", tmp_path, progress=lambda _m: None)
    assert sorted(p.name for p in target.glob("*.onnx")) == ["det.onnx", "rec.onnx"]
    assert set(verify_installed(target)) == {"det.onnx", "rec.onnx"}


def test_tampered_model_file_is_refused(tmp_path, monkeypatch):
    zip_path, digest = _pack(tmp_path)
    monkeypatch.setitem(model_store.KNOWN_PACKS, "testpack", (digest, 0.1))
    target = install_pack("testpack", tmp_path, progress=lambda _m: None)
    (target / "rec.onnx").write_bytes(b"swapped weights")
    with pytest.raises(ModelDownloadError, match="integrity check"):
        verify_installed(target)


def test_download_with_wrong_digest_is_rejected(tmp_path, monkeypatch):
    _pack(tmp_path)
    monkeypatch.setitem(model_store.KNOWN_PACKS, "testpack", ("0" * 64, 0.1))
    monkeypatch.setattr(model_store, "_download", lambda *a, **k: None)  # never touch the network
    with pytest.raises(ModelDownloadError, match="failed verification"):
        install_pack("testpack", tmp_path, progress=lambda _m: None)
    assert not (tmp_path / "models" / "testpack").exists()


def test_archive_path_traversal_is_refused(tmp_path, monkeypatch):
    zip_path, digest = _pack(tmp_path, files={"../evil.onnx": b"x"})
    monkeypatch.setitem(model_store.KNOWN_PACKS, "testpack", (digest, 0.1))
    with pytest.raises(ModelDownloadError, match="Unsafe path"):
        install_pack("testpack", tmp_path, progress=lambda _m: None)
    assert not (tmp_path / "evil.onnx").exists()


def test_unknown_pack_and_missing_install(tmp_path):
    with pytest.raises(ModelDownloadError, match="Unknown model pack"):
        install_pack("not-a-pack", tmp_path, progress=lambda _m: None)
    with pytest.raises(FaceModelUnavailable, match="download_face_models"):
        InsightFaceEngine("buffalo_l", tmp_path, det_size=1024, allow_download=False)


def test_record_checksums_format(tmp_path):
    (tmp_path / "a.onnx").write_bytes(b"abc")
    sums = record_checksums(tmp_path)
    assert sums["a.onnx"] == hashlib.sha256(b"abc").hexdigest()
    assert (tmp_path / "SHA256SUMS").read_text() == f"{sums['a.onnx']}  a.onnx\n"


class _FakeResponse:
    """Simulates a server that sends `chunks` and then closes the connection."""

    def __init__(self, body: bytes, total: int, status: int):
        self._body, self.status = body, status
        self.headers = {"Content-Length": str(total)}

    def read(self, _n):
        body, self._body = self._body, b""
        return body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_truncated_download_is_resumed_not_accepted(tmp_path, monkeypatch):
    payload = b"0123456789" * 100
    calls = []

    def fake_urlopen(request, timeout):
        rng = request.headers.get("Range")
        calls.append(rng)
        if rng is None:  # first attempt: server closes early after 300 bytes
            return _FakeResponse(payload[:300], len(payload), 200)
        start = int(rng.split("=")[1].rstrip("-"))
        return _FakeResponse(payload[start:], len(payload) - start, 206)

    monkeypatch.setattr(model_store.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(model_store.time, "sleep", lambda _s: None)
    target = tmp_path / "pack.zip"
    model_store._download("https://example.invalid/pack.zip", target, progress=lambda _m: None)
    assert target.read_bytes() == payload
    assert calls == [None, "bytes=300-"]  # resumed from where the truncated transfer stopped


# ── Phase 8: download safety ──────────────────────────────────────────────


class _RangeResponse(_FakeResponse):
    def __init__(self, body: bytes, start: int, full: int):
        super().__init__(body, len(body), 206)
        self.headers = {"Content-Length": str(len(body)), "Content-Range": f"bytes {start}-{full - 1}/{full}"}


def test_partial_larger_than_the_file_is_set_aside_not_appended(tmp_path, monkeypatch):
    """A .part longer than the real file (e.g. two writers appended to it) can never be resumed:
    the server answers 416. It is renamed (kept for inspection) and the download starts over."""
    import urllib.error

    payload = b"abcdefghij" * 100
    target = tmp_path / "pack.zip"
    partial = tmp_path / "pack.zip.part"
    partial.write_bytes(payload + b"garbage-appended-twice")

    def fake_urlopen(request, timeout):
        rng = request.headers.get("Range")
        if rng is not None:
            raise urllib.error.HTTPError(request.full_url, 416, "Range Not Satisfiable",
                                         {"Content-Range": f"bytes */{len(payload)}"}, None)
        return _FakeResponse(payload, len(payload), 200)

    monkeypatch.setattr(model_store.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(model_store.time, "sleep", lambda _s: None)
    model_store._download("https://example.invalid/pack.zip", target, progress=lambda _m: None)
    assert target.read_bytes() == payload
    kept = list(tmp_path.glob("pack.zip.part.corrupt-*"))
    assert len(kept) == 1 and kept[0].read_bytes() == payload + b"garbage-appended-twice"
    assert not (tmp_path / "pack.zip.part.lock").exists()


def test_resume_at_the_wrong_offset_starts_over(tmp_path, monkeypatch):
    payload = b"0123456789" * 50
    target = tmp_path / "pack.zip"
    (tmp_path / "pack.zip.part").write_bytes(payload[:200])
    calls = []

    def fake_urlopen(request, timeout):
        rng = request.headers.get("Range")
        calls.append(rng)
        if rng == "bytes=200-":  # a misbehaving server/proxy resumes from the wrong byte
            return _RangeResponse(payload[100:], 100, len(payload))
        return _FakeResponse(payload, len(payload), 200)

    monkeypatch.setattr(model_store.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(model_store.time, "sleep", lambda _s: None)
    model_store._download("https://example.invalid/pack.zip", target, progress=lambda _m: None)
    assert target.read_bytes() == payload  # never a spliced file
    assert calls == ["bytes=200-", None]


def test_only_one_download_writes_a_partial(tmp_path, monkeypatch):
    target = tmp_path / "pack.zip"
    (tmp_path / "pack.zip.part.lock").write_text("123")
    monkeypatch.setattr(model_store.urllib.request, "urlopen",
                        lambda *_a, **_k: pytest.fail("must not download while another writer holds the lock"))
    with pytest.raises(ModelDownloadError, match="Another download"):
        model_store._download("https://example.invalid/pack.zip", target, progress=lambda _m: None)
