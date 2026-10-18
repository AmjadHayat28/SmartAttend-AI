"""Synthetic test images. Faces are drawn shapes — no real people are used anywhere in tests."""

from __future__ import annotations

import cv2
import numpy as np


def face(size: int = 640, turn: int = 0, seed: int = 7) -> np.ndarray:
    """A cartoon face (BGR) that OpenCV's YuNet detector recognises. `turn` shifts the
    features sideways to mimic a slight left/right pose. Mild grain mimics a camera sensor."""
    img = np.full((size, size, 3), (90, 110, 130), np.uint8)
    c = size // 2
    cv2.ellipse(img, (c, c + 10), (int(size * .27), int(size * .35)), 0, 0, 360, (150, 180, 220), -1)
    for dx in (-1, 1):
        ex = c + dx * int(size * .105) + turn
        cv2.ellipse(img, (ex, c - int(size * .11)), (int(size * .065), int(size * .016)), 0, 0, 360, (40, 50, 60), -1)
        cv2.ellipse(img, (ex, c - int(size * .05)), (int(size * .05), int(size * .026)), 0, 0, 360, (255, 255, 255), -1)
        cv2.circle(img, (ex, c - int(size * .05)), int(size * .02), (30, 30, 30), -1)
    cv2.ellipse(img, (c + turn, c + int(size * .05)), (int(size * .03), int(size * .06)), 0, 0, 360, (120, 150, 190), -1)
    cv2.ellipse(img, (c + turn, c + int(size * .17)), (int(size * .08), int(size * .025)), 0, 0, 360, (70, 70, 160), -1)
    img = cv2.GaussianBlur(img, (0, 0), size / 400)
    grain = np.random.default_rng(seed).normal(0, 7, img.shape)
    return np.clip(img + grain, 0, 255).astype(np.uint8)


def two_faces() -> np.ndarray:
    return np.hstack([face(seed=1), face(seed=2)])


def no_face(size: int = 640) -> np.ndarray:
    """A textured scene with no face: gradient plus shapes plus grain."""
    ramp = np.tile(np.linspace(40, 200, size, dtype=np.float32), (size, 1))
    img = np.dstack([ramp, ramp[::-1], np.full_like(ramp, 120)])
    cv2.rectangle(img, (60, 80), (300, 260), (30, 160, 90), -1)
    cv2.circle(img, (450, 420), 110, (200, 60, 60), -1)
    grain = np.random.default_rng(3).normal(0, 6, img.shape)
    return np.clip(img + grain, 0, 255).astype(np.uint8)


def blank(size: int = 640, value: int = 128) -> np.ndarray:
    return np.full((size, size, 3), value, np.uint8)


def blurred(sigma: float = 9) -> np.ndarray:
    return cv2.GaussianBlur(face(), (0, 0), sigma)


def png(img: np.ndarray) -> bytes:
    return cv2.imencode(".png", img)[1].tobytes()


def jpeg(img: np.ndarray, quality: int = 92) -> bytes:
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])[1].tobytes()


def gif_bytes() -> bytes:
    from io import BytesIO

    from PIL import Image

    out = BytesIO()
    Image.new("RGB", (300, 300), (10, 120, 200)).save(out, format="GIF")
    return out.getvalue()


# Two cartoon "people" that a real face model detects and tells apart (same-person ~0.98,
# cross ~0.80 with InsightFace buffalo_sc). Used only by the opt-in real-model test.
PERSONAS = {
    "A": {},
    "C": dict(skin=(190, 205, 235), eye_dx=.09, eye_y=.02, mouth_w=.06, head=(.24, .38), nose_len=.09),
}


def persona(name: str, seed: int = 1, size: int = 640) -> np.ndarray:
    kw = {"skin": (150, 180, 220), "eye_dx": .105, "eye_y": .05, "mouth_w": .08, "head": (.27, .35),
          "brow": (40, 50, 60), "nose_len": .06, **PERSONAS[name]}
    img = np.full((size, size, 3), (90, 110, 130), np.uint8)
    c = size // 2
    cv2.ellipse(img, (c, c + 10), (int(size * kw["head"][0]), int(size * kw["head"][1])), 0, 0, 360, kw["skin"], -1)
    for dx in (-1, 1):
        ex = c + dx * int(size * kw["eye_dx"])
        cv2.ellipse(img, (ex, c - int(size * (kw["eye_y"] + .06))), (int(size * .065), int(size * .016)), 0, 0, 360, kw["brow"], -1)
        cv2.ellipse(img, (ex, c - int(size * kw["eye_y"])), (int(size * .05), int(size * .026)), 0, 0, 360, (255, 255, 255), -1)
        cv2.circle(img, (ex, c - int(size * kw["eye_y"])), int(size * .02), (30, 30, 30), -1)
    cv2.ellipse(img, (c, c + int(size * .05)), (int(size * .03), int(size * kw["nose_len"])), 0, 0, 360,
                tuple(int(v * .8) for v in kw["skin"]), -1)
    cv2.ellipse(img, (c, c + int(size * .17)), (int(size * kw["mouth_w"]), int(size * .025)), 0, 0, 360, (70, 70, 160), -1)
    img = cv2.GaussianBlur(img, (0, 0), size / 400)
    return np.clip(img + np.random.default_rng(seed).normal(0, 7, img.shape), 0, 255).astype(np.uint8)
