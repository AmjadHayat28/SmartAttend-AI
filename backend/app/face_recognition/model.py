"""InsightFace engine: SCRFD face detector + ArcFace embedder, loaded once per process.

Model pack: settings.FACE_RECOGNITION_MODEL (default "buffalo_l" = det_10g.onnx detector +
w600k_r50.onnx ArcFace ResNet-50, 512-d embeddings). Only the detection and recognition models
are loaded (no age/gender/landmark extras). Packs live in settings.FACE_RECOGNITION_MODEL_DIR
(git-ignored models_cache/) and are installed by model_store.install_pack, which verifies the
download against the SHA-256 published on the official InsightFace GitHub release and records
per-file checksums that are re-verified on every load.

Licensing: InsightFace's pretrained packs ship under its non-commercial terms unless a signed
commercial MODEL.LICENSE is obtained from InsightFace. Review before production use.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from backend.app.core.config import settings
from backend.app.face_recognition.classroom import ClassroomDetectConfig, ClassroomDetection, detect_classroom
from backend.app.face_recognition.model_store import ModelDownloadError, install_pack, pack_dir, verify_installed
from backend.app.face_recognition.types import FaceEngine, FaceObservation

log = logging.getLogger("smartclass.recognition")

_ENROLLMENT_DET_SIZES = [(640, 640)]  # one large, centred face


class FaceModelUnavailable(RuntimeError):
    """The recognition model cannot be loaded (missing, failed integrity check, …)."""


@dataclass
class ClassroomAnalysis:
    """Faces of one classroom photo plus non-sensitive diagnostics (no vectors, no pixels)."""

    faces: list[FaceObservation]
    detection: ClassroomDetection
    embedding_ms: float


def classroom_config() -> ClassroomDetectConfig:
    """Detection settings for group photos (read per call so configuration changes apply)."""
    det = settings.FACE_RECOGNITION_DET_SIZE
    return ClassroomDetectConfig(
        sizes=tuple(sorted({(640, 640), (det, det)})), tiling=settings.FACE_RECOGNITION_TILING,
        tile_size=settings.FACE_RECOGNITION_TILE_SIZE, tile_overlap=settings.FACE_RECOGNITION_TILE_OVERLAP,
        auto_orient=settings.FACE_RECOGNITION_AUTO_ORIENT, nms_iou=settings.FACE_RECOGNITION_NMS_IOU,
    )


class InsightFaceEngine:
    def __init__(self, name: str, root: Path, det_size: int, allow_download: bool):
        model_dir = pack_dir(root, name)
        try:
            if not (model_dir / "SHA256SUMS").exists():
                if not allow_download:
                    raise FaceModelUnavailable(
                        f"Face recognition model '{name}' is not installed. Run: "
                        "uv run python -m backend.app.scripts.download_face_models")
                install_pack(name, root, progress=log.info)
            hashes = verify_installed(model_dir)
        except ModelDownloadError as exc:
            raise FaceModelUnavailable(str(exc)) from exc
        try:
            from insightface.app import FaceAnalysis  # heavy import, kept local

            # Passing the directory (not the pack name) means InsightFace never downloads anything.
            self._app = FaceAnalysis(name=str(model_dir), allowed_modules=["detection", "recognition"],
                                     providers=["CPUExecutionProvider"])
            self._app.prepare(ctx_id=-1, det_size=(det_size, det_size))
        except FaceModelUnavailable:
            raise
        except Exception as exc:
            raise FaceModelUnavailable(f"Face recognition model could not be loaded ({type(exc).__name__}).") from exc
        rec = self._app.models.get("recognition")
        if rec is None:
            raise FaceModelUnavailable(f"Model pack '{name}' has no recognition model.")
        rec_file = Path(getattr(rec, "model_file", "")).name
        self.model_name = f"insightface/{name}"
        # Changes whenever the recognition weights change → embeddings are regenerated.
        self.model_version = f"{rec_file}:{hashes.get(rec_file, 'unknown')[:16]}"
        self.dimension = int(rec.output_shape[-1]) if getattr(rec, "output_shape", None) else 512
        det_file = Path(getattr(self._app.det_model, "model_file", "")).name or "detector"
        self.detector_name = f"SCRFD {det_file}"
        self.pack = name
        self.fallback_from: str | None = None  # set by load_engine when this pack is the fallback
        self._lock = threading.Lock()

    def _detect(self, img: np.ndarray, sizes: list[tuple[int, int]]):
        return self._app.det_model.detect(img, input_size=sizes, max_num=0,
                                          det_thresh=settings.FACE_RECOGNITION_MIN_DET_SCORE)

    def _embed(self, image_bgr: np.ndarray, boxes: np.ndarray, kpss: np.ndarray | None) -> list[FaceObservation]:
        """ArcFace embedding per face, aligned on the ORIGINAL image with its 5 landmarks."""
        from insightface.app.common import Face

        rec = self._app.models["recognition"]
        out = []
        for i in range(boxes.shape[0]):
            face = Face(bbox=boxes[i, 0:4], kps=kpss[i] if kpss is not None else None, det_score=boxes[i, 4])
            rec.get(image_bgr, face)  # similarity-transform alignment (handles in-plane rotation)
            x1, y1, x2, y2 = (float(v) for v in face.bbox)
            emb = np.asarray(face.embedding, dtype=np.float32)
            emb = emb / (np.linalg.norm(emb) or 1.0)
            out.append(FaceObservation(bbox=(max(0, round(x1)), max(0, round(y1)), round(x2 - x1), round(y2 - y1)),
                                       det_score=float(face.det_score), embedding=emb))
        return out

    @contextmanager
    def _reuse_identical_passes(self):
        """Within one photo, run each identical detector pass only once.

        The upright orientation check and the full-image pass both run the detector on the same
        array at 640 px; the second is a pure repeat (measured: same candidates, ~0.5 s per photo).
        SCRFD.detect() scores each input size separately (_detect_candidates) before one joint NMS,
        so memoising that step per (array, size, threshold) changes nothing in the results. If the
        installed InsightFace has no such step, detection simply runs unmemoised."""
        det = self._app.det_model
        inner = getattr(det, "_detect_candidates", None)
        if inner is None:
            yield
            return
        memo: dict[tuple, tuple[np.ndarray, object]] = {}

        def detect_candidates(img, input_size, threshold):
            key = (id(img), tuple(int(v) for v in input_size), float(threshold))
            hit = memo.get(key)
            if hit is not None and hit[0] is img:  # the array is held below, so its id is not reused
                return hit[1]
            result = inner(img, input_size, threshold)
            memo[key] = (img, result)
            return result

        det._detect_candidates = detect_candidates
        try:
            yield
        finally:
            del det._detect_candidates  # back to the class method
            memo.clear()

    def analyze_classroom(self, image_bgr: np.ndarray) -> ClassroomAnalysis:
        """Group photo: orientation + multi-scale + optional tiles, merged; boxes in original pixels."""
        with self._lock:  # the onnxruntime sessions are shared; serialise inference
            with self._reuse_identical_passes():
                detection = detect_classroom(self._detect, image_bgr, classroom_config())
            started = time.perf_counter()
            faces = self._embed(image_bgr, detection.boxes, detection.kps)
        return ClassroomAnalysis(faces=faces, detection=detection, embedding_ms=(time.perf_counter() - started) * 1000)

    def analyze(self, image_bgr: np.ndarray, *, purpose: str) -> list[FaceObservation]:
        if purpose != "enrollment":
            return self.analyze_classroom(image_bgr).faces
        with self._lock:
            boxes, kpss = self._app.det_model.detect(image_bgr, input_size=_ENROLLMENT_DET_SIZES, max_num=0)
            return self._embed(image_bgr, boxes, kpss)


_engine: FaceEngine | None = None
_engine_lock = threading.Lock()


def _load(name: str) -> InsightFaceEngine:
    return InsightFaceEngine(name, Path(settings.FACE_RECOGNITION_MODEL_DIR), settings.FACE_RECOGNITION_DET_SIZE,
                             settings.FACE_RECOGNITION_ALLOW_DOWNLOAD)


def load_engine(primary: str, fallback: str | None, loader=None):
    """Load `primary`; if it cannot be loaded and a different `fallback` is configured, load that
    instead and record `fallback_from` so every recognition run reports it. Never silent."""
    loader = loader or _load
    try:
        return loader(primary)
    except FaceModelUnavailable as exc:
        if not fallback or fallback == primary:
            raise
        log.warning("Face model %s unavailable (%s); falling back to %s", primary, exc, fallback)
        try:
            engine = loader(fallback)
        except FaceModelUnavailable as fallback_exc:
            raise FaceModelUnavailable(f"{exc} Fallback {fallback!r}: {fallback_exc}") from fallback_exc
        engine.fallback_from = primary
        return engine


_failure: tuple[float, FaceModelUnavailable] | None = None  # (monotonic time, error) of the last failed load


def get_engine() -> FaceEngine:
    """The process-wide engine, created on first use (thread-safe) and then reused: models are
    loaded once per process, never per photo or per face. A fallback engine stays in use until
    restart (the log and every run's diagnostics say so). After a failed load, requests are
    refused at once for FACE_RECOGNITION_RETRY_SECONDS instead of re-hashing the model files on
    every request; then loading is retried."""
    global _engine, _failure
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                if _failure is not None and time.monotonic() - _failure[0] < settings.FACE_RECOGNITION_RETRY_SECONDS:
                    raise _failure[1]
                started = time.perf_counter()
                try:
                    engine = load_engine(settings.FACE_RECOGNITION_MODEL, settings.FACE_RECOGNITION_FALLBACK_MODEL or None)
                except FaceModelUnavailable as exc:
                    _failure = (time.monotonic(), exc)
                    log.error("Face recognition is UNAVAILABLE: model %r could not be loaded: %s "
                              "Next load attempt in %ss.", settings.FACE_RECOGNITION_MODEL, exc,
                              settings.FACE_RECOGNITION_RETRY_SECONDS)
                    raise
                _engine, _failure = engine, None
                fallback_from = getattr(engine, "fallback_from", None)
                (log.warning if fallback_from else log.info)(
                    "Loaded %s (%s, dim=%s, detector=%s) in %.1f s%s", engine.model_name, engine.model_version,
                    engine.dimension, getattr(engine, "detector_name", "?"), time.perf_counter() - started,
                    f" — FALLBACK: configured model {fallback_from!r} is unavailable" if fallback_from else "")
    return _engine


def engine_status() -> str:
    """For readiness checks, without loading anything: "disabled", "ready", "fallback" (the
    configured model failed; a lower-accuracy one is in use), "loading", "unavailable" (last load
    failed) or "not_loaded" (loads on first use)."""
    if not settings.FACE_RECOGNITION_ENABLED:
        return "disabled"
    if _engine is not None:
        return "fallback" if getattr(_engine, "fallback_from", None) else "ready"
    if _engine_lock.locked():
        return "loading"
    return "unavailable" if _failure is not None else "not_loaded"


def preload_engine() -> None:
    """Load the engine ahead of the first recognition run (called in a background thread at
    startup). Never raises: a failure is logged and the next run reports it to the teacher."""
    try:
        get_engine()
    except FaceModelUnavailable:
        pass  # already logged by get_engine
    except Exception:  # pragma: no cover - defensive
        log.exception("Face recognition model preload failed")


def set_engine(engine: FaceEngine | None) -> None:
    """Replace the engine (tests use a deterministic fake; None = load the real one lazily)."""
    global _engine, _failure
    with _engine_lock:
        _engine, _failure = engine, None
