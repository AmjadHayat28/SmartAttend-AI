"""Face enrollment data.

Phase 4 stores validated registration photos; embeddings are produced in Phase 6.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database.base import Base
from backend.app.models.attendance import JSONType
from backend.app.models.enums import FaceImageType, ImageCheckStatus, str_enum

if TYPE_CHECKING:
    from backend.app.models.people import Student


class StudentFaceImage(Base):
    __tablename__ = "student_face_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    # Relative to UPLOAD_DIR, e.g. "faces/12/3f2a….jpg". Never returned by the API.
    image_path: Mapped[str] = mapped_column(String(500))
    image_type: Mapped[FaceImageType] = mapped_column(str_enum(FaceImageType))  # pose
    is_usable: Mapped[bool] = mapped_column(Boolean, default=True)
    # Result of server-side validation. Only PASS/WARNING images are stored; FAIL uploads are refused.
    validation_status: Mapped[ImageCheckStatus] = mapped_column(
        str_enum(ImageCheckStatus), default=ImageCheckStatus.PASS, server_default=ImageCheckStatus.PASS.value
    )
    validation_message: Mapped[str | None] = mapped_column(Text)
    # Per-check results + detected face box/score (metadata only — never pixels).
    quality: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    file_size: Mapped[int | None] = mapped_column(Integer)  # bytes of the stored (re-encoded) file
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())  # uploaded
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )  # last replaced
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    student: Mapped[Student] = relationship(back_populates="face_images")
    embedding: Mapped[FaceEmbedding | None] = relationship(back_populates="face_image", uselist=False)


class FaceEmbedding(Base):
    """One embedding per approved registration image (front/left/right/extra).

    `embedding_vector` holds L2-normalised float32 bytes (numpy.ndarray.tobytes()), portable
    across PostgreSQL and SQLite. It is biometric data: never returned by the API, never logged.

    Freshness: a row is valid only while `model_name`/`model_version` match the running model
    and `source_updated_at` equals its face image's `updated_at`. Rows are deleted when the
    enrollment is sent back for a retake, and regenerated after (re-)approval.
    """

    __tablename__ = "face_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    face_image_id: Mapped[int] = mapped_column(
        ForeignKey("student_face_images.id", ondelete="CASCADE"), unique=True
    )
    embedding_vector: Mapped[bytes] = mapped_column(LargeBinary)
    dimension: Mapped[int] = mapped_column(Integer)  # e.g. 512 for ArcFace
    model_name: Mapped[str] = mapped_column(String(100))  # e.g. "insightface/buffalo_l"
    model_version: Mapped[str] = mapped_column(String(100), default="", server_default="")
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    det_score: Mapped[float | None] = mapped_column(Float)  # detector confidence on the source photo
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped[Student] = relationship(back_populates="face_embeddings")
    face_image: Mapped[StudentFaceImage] = relationship(back_populates="embedding")
