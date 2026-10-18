"""Server-side validation for uploaded profile and face-enrollment photos.

Nothing about the upload is trusted: not the filename, not the extension, not the declared
content type. The bytes must decode as a JPEG or PNG whose real format matches the declared
type. Accepted images are re-encoded to a fresh JPEG, which also strips EXIF/GPS metadata and
any trailing payload. Validation results are metadata only — pixels never reach logs.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from backend.app.core.config import settings
from backend.app.face_recognition.detection import detect_faces
from backend.app.models import ImageCheckStatus

# Declared MIME type → the format Pillow must actually find in the bytes.
_FORMATS = {"image/jpeg": "JPEG", "image/jpg": "JPEG", "image/pjpeg": "JPEG", "image/png": "PNG"}
_JPEG_QUALITY = 92


class ImageRejected(Exception):
    """Upload refused. `message` is safe to show to the user; `status_code` is the HTTP code."""

    def __init__(self, message: str, status_code: int = 422, checks: list[dict] | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.checks = checks or []


@dataclass
class ProcessedImage:
    jpeg: bytes  # re-encoded image to store
    width: int
    height: int
    status: ImageCheckStatus = ImageCheckStatus.PASS
    message: str | None = None
    checks: list[dict[str, Any]] = field(default_factory=list)
    face: dict[str, Any] | None = None

    @property
    def quality(self) -> dict[str, Any]:
        return {"checks": self.checks, "face": self.face}


def max_upload_bytes() -> int:
    return int(settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024)


def _decode(data: bytes, content_type: str | None) -> Image.Image:
    if not data:
        raise ImageRejected("The file is empty.")
    if len(data) > max_upload_bytes():
        raise ImageRejected(f"Image is too large. The maximum size is {settings.MAX_UPLOAD_SIZE_MB:g} MB.", 413)
    declared = (content_type or "").split(";")[0].strip().lower()
    allowed = {t.lower() for t in settings.ALLOWED_IMAGE_TYPES}
    if declared not in allowed or declared not in _FORMATS:
        raise ImageRejected("Unsupported image format. Please upload a JPEG or PNG photo.", 415)
    try:
        image = Image.open(io.BytesIO(data))
        if image.format != _FORMATS[declared]:
            if image.format in _FORMATS.values():
                raise ImageRejected("The file content does not match its declared type.", 415)
            raise ImageRejected("Unsupported image format. Please upload a JPEG or PNG photo.", 415)
        width, height = image.size
        if width * height > settings.IMAGE_MAX_PIXELS:  # checked from the header, before decoding
            raise ImageRejected(
                f"Image dimensions are too large ({width}×{height}). The maximum is "
                f"{settings.IMAGE_MAX_PIXELS / 1_000_000:g} megapixels — use the camera's standard photo mode.")
        image.load()  # full decode: truncated/corrupt files fail here
        image = ImageOps.exif_transpose(image)  # respect phone camera orientation
    except ImageRejected:
        raise
    except Image.DecompressionBombError:  # Pillow's own guard, raised from the header for extreme sizes
        raise ImageRejected(
            f"Image dimensions are too large. The maximum is {settings.IMAGE_MAX_PIXELS / 1_000_000:g} megapixels "
            "— use the camera's standard photo mode.") from None
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise ImageRejected("The image is corrupt or unreadable. Please choose another photo.") from None
    if image.width == 0 or image.height == 0:
        raise ImageRejected("The image is corrupt or unreadable. Please choose another photo.")
    if image.mode != "RGB":
        background = Image.new("RGB", image.size, (255, 255, 255))
        rgba = image.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    return image


def _check_size(image: Image.Image) -> dict:
    short = min(image.size)
    if short < settings.IMAGE_MIN_DIMENSION:
        raise ImageRejected(
            f"Image is too small. Use a photo at least {settings.IMAGE_MIN_DIMENSION}×{settings.IMAGE_MIN_DIMENSION} pixels."
        )
    if short < settings.IMAGE_RECOMMENDED_MIN_DIMENSION:
        return _check("resolution", ImageCheckStatus.WARNING, f"Low resolution ({image.width}×{image.height}).", short)
    return _check("resolution", ImageCheckStatus.PASS, None, short)


def _check(name: str, status: ImageCheckStatus, message: str | None, value: float) -> dict:
    return {"check": name, "status": status.value, "message": message, "value": round(float(value), 2)}


def _encode(image: Image.Image, longest: int | None = None) -> tuple[bytes, int, int]:
    longest = longest or settings.IMAGE_STORE_MAX_DIMENSION
    if max(image.size) > longest:
        image = image.copy()
        image.thumbnail((longest, longest), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=_JPEG_QUALITY, optimize=True)  # no EXIF carried over
    return out.getvalue(), image.width, image.height


def _summarise(processed: ProcessedImage) -> ProcessedImage:
    warnings = [c["message"] for c in processed.checks if c["status"] == ImageCheckStatus.WARNING.value]
    processed.status = ImageCheckStatus.WARNING if warnings else ImageCheckStatus.PASS
    processed.message = " ".join(warnings) or None
    return processed


def validate_profile_photo(data: bytes, content_type: str | None) -> ProcessedImage:
    image = _decode(data, content_type)
    checks = [_check_size(image)]
    grey = np.asarray(image.convert("L"), dtype=np.float32)
    if grey.std() < settings.IMAGE_BLANK_STDDEV:
        raise ImageRejected("The image appears to be blank. Please choose another photo.")
    jpeg, width, height = _encode(image)
    return _summarise(ProcessedImage(jpeg=jpeg, width=width, height=height, checks=checks))


def validate_face_photo(data: bytes, content_type: str | None) -> ProcessedImage:
    """Full enrollment-photo validation: decode, size, blank, exactly-one-face, blur, exposure."""
    image = _decode(data, content_type)
    checks = [_check_size(image)]
    rgb = np.asarray(image)
    grey = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if float(grey.std()) < settings.IMAGE_BLANK_STDDEV:
        raise ImageRejected("The image appears to be blank. Please upload a clear photo of your face.")

    short = min(image.size)
    faces = [f for f in detect_faces(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), settings.FACE_DETECTION_SCORE)
             if f.min_side >= settings.FACE_MIN_SIZE_RATIO * short]
    if not faces:
        raise ImageRejected("No face detected. Please upload a clearer photo.")
    if len(faces) > 1:
        raise ImageRejected("Multiple faces detected. Please upload a photo containing only yourself.")
    face = faces[0]

    ratio = face.min_side / short
    if ratio < settings.FACE_RECOMMENDED_SIZE_RATIO:
        checks.append(_check("face_size", ImageCheckStatus.WARNING, "Your face is small in the frame; move closer.", ratio))
    else:
        checks.append(_check("face_size", ImageCheckStatus.PASS, None, ratio))

    # Quality is measured on the face itself, normalised to a fixed width so the blur
    # score does not depend on the photo's resolution.
    x0, y0 = max(0, face.x), max(0, face.y)
    x1, y1 = min(grey.shape[1], face.x + face.width), min(grey.shape[0], face.y + face.height)
    crop = grey[y0:y1, x0:x1]
    if crop.size == 0:
        raise ImageRejected("No face detected. Please upload a clearer photo.")
    crop = cv2.resize(crop, (256, max(1, round(256 * crop.shape[0] / crop.shape[1]))), interpolation=cv2.INTER_AREA)

    sharpness = float(cv2.Laplacian(crop, cv2.CV_64F).var())
    if sharpness < settings.FACE_BLUR_FAIL:
        raise ImageRejected("The photo is too blurry. Hold the camera steady and retake it.",
                            checks=checks + [_check("blur", ImageCheckStatus.FAIL, "Too blurry", sharpness)])
    checks.append(_check("blur", ImageCheckStatus.WARNING if sharpness < settings.FACE_BLUR_WARN else ImageCheckStatus.PASS,
                         "The photo is slightly blurry." if sharpness < settings.FACE_BLUR_WARN else None, sharpness))

    brightness = float(crop.mean())
    if brightness < settings.FACE_BRIGHTNESS_FAIL_LOW:
        raise ImageRejected("The photo is too dark. Retake it in better light.")
    if brightness > settings.FACE_BRIGHTNESS_FAIL_HIGH:
        raise ImageRejected("The photo is overexposed. Avoid strong light directly on your face and retake it.")
    if brightness < settings.FACE_BRIGHTNESS_WARN_LOW:
        checks.append(_check("brightness", ImageCheckStatus.WARNING, "The lighting is a little dark.", brightness))
    elif brightness > settings.FACE_BRIGHTNESS_WARN_HIGH:
        checks.append(_check("brightness", ImageCheckStatus.WARNING, "The lighting is a little bright.", brightness))
    else:
        checks.append(_check("brightness", ImageCheckStatus.PASS, None, brightness))

    jpeg, width, height = _encode(image)
    scale = width / image.width  # face box in the stored image's coordinates (for Phase 6 cropping)
    face_meta = {"x": round(face.x * scale), "y": round(face.y * scale), "width": round(face.width * scale),
                 "height": round(face.height * scale), "score": face.score}
    return _summarise(ProcessedImage(jpeg=jpeg, width=width, height=height, checks=checks, face=face_meta))


def validate_classroom_photo(data: bytes, content_type: str | None) -> ProcessedImage:
    """Classroom (group) photo for an attendance session.

    Same decode/type/size/metadata rules as enrollment photos, but no face rule: a classroom
    photo is expected to contain many people, and nothing is detected or recognised here
    (that is Phase 6). Stored at a higher resolution so small faces survive for later use.
    """
    image = _decode(data, content_type)
    short = min(image.size)
    if short < settings.ATTENDANCE_PHOTO_MIN_DIMENSION:
        raise ImageRejected(
            f"Image is too small. Classroom photos must be at least {settings.ATTENDANCE_PHOTO_MIN_DIMENSION} "
            "pixels on the shorter side."
        )
    if max(image.size) / short > settings.ATTENDANCE_PHOTO_MAX_ASPECT_RATIO:
        raise ImageRejected(
            f"This image is too long and narrow ({image.width}×{image.height}) to be a classroom photo. "
            "Please take a normal photo of the class."
        )
    grey = np.asarray(image.convert("L"), dtype=np.float32)
    if grey.std() < settings.IMAGE_BLANK_STDDEV:
        raise ImageRejected("The image appears to be blank. Please choose another photo.")
    jpeg, width, height = _encode(image, settings.ATTENDANCE_PHOTO_MAX_DIMENSION)
    checks = [_check("resolution", ImageCheckStatus.PASS, None, short)]
    return _summarise(ProcessedImage(jpeg=jpeg, width=width, height=height, checks=checks))
