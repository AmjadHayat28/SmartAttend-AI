"""Deterministic stand-in for the InsightFace engine (no model files, no network, no real faces).

- Enrollment photos: one face whose embedding is derived from the image content (stable per
  photo), so generation/freshness logic is exercised for real.
- Classroom photos: tests register exactly which faces a photo of a given size contains,
  with synthetic unit vectors chosen to hit specific similarities.
"""

from __future__ import annotations

import hashlib

import numpy as np

from backend.app.face_recognition.types import FaceObservation

DIM = 512  # same size as ArcFace embeddings; keeps random cross-similarity small


def unit(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    return (v / np.linalg.norm(v)).astype(np.float32)


def random_identity(seed: int) -> np.ndarray:
    return unit(np.random.default_rng(seed).normal(size=DIM))


def with_similarity(base: np.ndarray, similarity: float, seed: int = 0) -> np.ndarray:
    """A unit vector whose cosine similarity to `base` is exactly `similarity`."""
    base = unit(base).astype(np.float64)
    noise = np.random.default_rng(10_000 + seed).normal(size=DIM)
    orth = noise - noise.dot(base) * base
    orth /= np.linalg.norm(orth)
    return unit(similarity * base + np.sqrt(max(0.0, 1 - similarity**2)) * orth)


class FakeEngine:
    model_name = "fake/test-engine"
    dimension = DIM

    def __init__(self, version: str = "v1"):
        self.model_version = version
        self.classroom: dict[tuple[int, int], list[FaceObservation]] = {}
        self.calls = 0
        self.fail_on_classroom = False

    def add_photo(self, width: int, height: int, embeddings: list[np.ndarray]) -> None:
        """Declare the faces a classroom photo of this size contains (boxes laid out in a row)."""
        faces = []
        for i, emb in enumerate(embeddings):
            faces.append(FaceObservation(bbox=(20 + i * 70, 40, 60, 60), det_score=0.9, embedding=unit(emb)))
        self.classroom[(width, height)] = faces

    def analyze(self, image_bgr: np.ndarray, *, purpose: str) -> list[FaceObservation]:
        self.calls += 1
        h, w = image_bgr.shape[:2]
        if purpose == "enrollment":
            small = np.ascontiguousarray(image_bgr[::16, ::16])
            seed = int.from_bytes(hashlib.sha256(small.tobytes()).digest()[:8], "little")
            return [FaceObservation(bbox=(w // 4, h // 4, w // 2, h // 2), det_score=0.95,
                                    embedding=random_identity(seed))]
        if self.fail_on_classroom:
            raise RuntimeError("simulated inference crash")
        return list(self.classroom.get((w, h), []))


def blend(targets: list[tuple[np.ndarray, float]], seed: int = 0) -> np.ndarray:
    """A unit vector with (approximately exactly) the given cosine similarity to each target."""
    basis = np.stack([unit(t).astype(np.float64) for t, _ in targets])
    sims = np.array([s for _, s in targets], dtype=np.float64)
    alpha = np.linalg.solve(basis @ basis.T, sims)  # v = basisᵀ·alpha satisfies basis·v = sims
    v = basis.T @ alpha
    rest = 1.0 - float(v @ v)
    noise = np.random.default_rng(20_000 + seed).normal(size=DIM)
    noise -= basis.T @ np.linalg.lstsq(basis.T, noise, rcond=None)[0]  # orthogonal to all targets
    noise /= np.linalg.norm(noise)
    return unit(v + np.sqrt(max(rest, 0.0)) * noise)
