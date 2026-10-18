"""Plain data types shared by the recognition pipeline. No vectors ever leave the backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from backend.app.models.enums import RecognitionCategory as MatchCategory  # single definition


@dataclass(frozen=True)
class FaceObservation:
    """One detected face: box in image pixels, detector score, L2-normalised embedding."""

    bbox: tuple[int, int, int, int]  # x, y, width, height
    det_score: float
    embedding: np.ndarray  # float32, shape (dim,), unit length


class FaceEngine(Protocol):
    """Detection + embedding backend. Real: InsightFace. Tests: a deterministic fake."""

    model_name: str  # e.g. "insightface/buffalo_l"
    model_version: str  # changes whenever embeddings become incompatible
    dimension: int

    def analyze(self, image_bgr: np.ndarray, *, purpose: str) -> list[FaceObservation]:
        """purpose: "enrollment" (one large face) or "classroom" (many, possibly small)."""
        ...


@dataclass
class Candidate:
    """A roster student's approved embeddings, stacked (k × dim)."""

    student_id: int
    vectors: np.ndarray


@dataclass
class FaceMatch:
    image_id: int
    face_index: int
    bbox: tuple[int, int, int, int]
    det_score: float
    category: MatchCategory
    student_id: int | None = None  # suggested/assigned student
    similarity: float | None = None
    second_student_id: int | None = None
    second_similarity: float | None = None
    is_primary: bool = True  # False = this student's best sighting is in another photo


@dataclass
class Thresholds:
    confident: float
    low: float
    margin: float

    def as_dict(self) -> dict:
        return {"confident": self.confident, "low": self.low, "margin": self.margin}


@dataclass
class ImageFaces:
    image_id: int
    faces: list[FaceObservation] = field(default_factory=list)
