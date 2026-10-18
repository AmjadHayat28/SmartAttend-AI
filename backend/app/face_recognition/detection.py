"""Lightweight face *detection* for enrollment-photo validation (Phase 4).

Uses OpenCV's built-in YuNet detector (cv2.FaceDetectorYN). OpenCV 5 no longer ships the
legacy Haar cascades, and YuNet copes with the slight left/right poses we ask students for.
The ~230 KB model (MIT licence, github.com/opencv/opencv_zoo) is bundled in ./models and
verified by SHA-256 before loading. OpenCV runs it natively — no ONNX Runtime needed.

This module only finds faces. It does not identify anyone and produces no embeddings.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

MODEL_PATH = Path(__file__).with_name("models") / "face_detection_yunet_2023mar.onnx"
MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
_DETECT_MAX_SIDE = 640  # detection runs on a downscaled copy for speed

try:  # OpenCV prints harmless backend notices for every detector instance
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except AttributeError:  # pragma: no cover - older builds
    pass


@dataclass(frozen=True)
class DetectedFace:
    x: int
    y: int
    width: int
    height: int
    score: float

    @property
    def min_side(self) -> int:
        return min(self.width, self.height)


class FaceDetectorUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _detector() -> tuple[cv2.FaceDetectorYN, threading.Lock]:
    if not MODEL_PATH.is_file():
        raise FaceDetectorUnavailable(f"Face detection model missing: {MODEL_PATH.name}")
    digest = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
    if digest != MODEL_SHA256:
        raise FaceDetectorUnavailable("Face detection model failed its integrity check")
    detector = cv2.FaceDetectorYN.create(str(MODEL_PATH), "", (320, 320), 0.5, 0.3, 50)
    return detector, threading.Lock()


def detect_faces(image_bgr: np.ndarray, score_threshold: float) -> list[DetectedFace]:
    """Return faces found in a BGR image, in the image's own pixel coordinates."""
    height, width = image_bgr.shape[:2]
    scale = min(1.0, _DETECT_MAX_SIDE / max(height, width))
    small = image_bgr if scale == 1.0 else cv2.resize(
        image_bgr, (max(1, round(width * scale)), max(1, round(height * scale))), interpolation=cv2.INTER_AREA
    )
    detector, lock = _detector()
    with lock:  # the detector object is stateful (input size, threshold)
        detector.setInputSize((small.shape[1], small.shape[0]))
        detector.setScoreThreshold(score_threshold)
        _, rows = detector.detect(small)
    if rows is None:
        return []
    faces = []
    for row in rows:
        x, y, w, h = (float(v) / scale for v in row[:4])
        faces.append(DetectedFace(x=max(0, round(x)), y=max(0, round(y)), width=round(w), height=round(h),
                                  score=round(float(row[14]), 3)))
    return sorted(faces, key=lambda f: f.width * f.height, reverse=True)
