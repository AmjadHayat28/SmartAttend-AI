"""Private image storage.

Production:
- Uses Cloudinary authenticated assets when Cloudinary credentials are configured.
- Database still stores only server-generated relative identifiers.
- Images remain accessible only through our authorised backend endpoints.

Development:
- Falls back to local filesystem storage under settings.UPLOAD_DIR.
"""

from __future__ import annotations

import io
import os
import re
import uuid
from pathlib import Path
from typing import Literal

import requests

from backend.app.core.config import settings

Area = Literal["faces", "profiles", "attendance"]

_STORED_PATH = re.compile(
    r"^(faces|profiles|attendance)/[1-9][0-9]{0,9}/[0-9a-f]{32}\.jpg$"
)


class StorageError(Exception):
    pass


def cloudinary_enabled() -> bool:
    return bool(
        os.environ.get("CLOUDINARY_CLOUD_NAME")
        and os.environ.get("CLOUDINARY_API_KEY")
        and os.environ.get("CLOUDINARY_API_SECRET")
    )


def _vercel_production() -> bool:
    return os.environ.get("VERCEL") == "1" and os.environ.get("VERCEL_ENV") == "production"


def validate_runtime_storage() -> None:
    """Called at startup, never on import: model builds do not need storage secrets."""
    if _vercel_production() and not cloudinary_enabled():
        raise StorageError(
            "Vercel production requires CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and "
            "CLOUDINARY_API_SECRET. Refusing ephemeral local upload storage."
        )


def ready() -> bool:
    """Configuration/local readiness only; no remote calls or credential disclosure."""
    if cloudinary_enabled():
        return True
    if _vercel_production():
        return False
    root = Path(settings.UPLOAD_DIR)
    return root.is_dir() and os.access(root, os.W_OK)


def _configure_cloudinary():
    import cloudinary

    cloudinary.config(
        cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key=os.environ["CLOUDINARY_API_KEY"],
        api_secret=os.environ["CLOUDINARY_API_SECRET"],
        secure=True,
    )


def _root() -> Path:
    return Path(settings.UPLOAD_DIR).resolve()


def resolve(relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not _STORED_PATH.fullmatch(relative_path):
        raise StorageError("Invalid stored path")

    root = _root()
    path = (root / Path(*relative_path.split("/"))).resolve()

    if not path.is_relative_to(root):
        raise StorageError("Invalid stored path")

    return path


def _validate(relative_path: str) -> str:
    if not isinstance(relative_path, str) or not _STORED_PATH.fullmatch(relative_path):
        raise StorageError("Invalid stored path")
    return relative_path


def _public_id(relative_path: str) -> str:
    relative_path = _validate(relative_path)
    return relative_path[:-4]  # remove .jpg


def save(area: Area, owner_id: int, data: bytes, suffix: str = ".jpg") -> str:
    if (
        area not in ("faces", "profiles", "attendance")
        or not isinstance(owner_id, int)
        or owner_id <= 0
        or suffix != ".jpg"
    ):
        raise StorageError("Invalid storage target")

    relative = f"{area}/{owner_id}/{uuid.uuid4().hex}{suffix}"

    if cloudinary_enabled():
        try:
            import cloudinary.uploader

            _configure_cloudinary()

            stream = io.BytesIO(data)
            stream.name = "image.jpg"

            cloudinary.uploader.upload(
                stream,
                public_id=_public_id(relative),
                resource_type="image",
                type="authenticated",
                format="jpg",
                overwrite=False,
            )
            return relative
        except Exception as exc:
            raise StorageError("Cloud image upload failed") from exc

    target = resolve(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")

    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)

    return relative


def read(relative_path: str) -> bytes:
    if cloudinary_enabled():
        try:
            import cloudinary.utils

            _configure_cloudinary()

            url = cloudinary.utils.private_download_url(
                _public_id(relative_path),
                "jpg",
                resource_type="image",
                type="authenticated",
            )

            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.content
        except Exception as exc:
            raise StorageError("File not found") from exc

    path = resolve(relative_path)

    if not path.is_file():
        raise StorageError("File not found")

    return path.read_bytes()


def prune_dir(area: Area, owner_id: int) -> None:
    if (
        area not in ("faces", "profiles", "attendance")
        or not isinstance(owner_id, int)
        or owner_id <= 0
    ):
        return

    if cloudinary_enabled():
        return

    try:
        (_root() / area / str(owner_id)).rmdir()
    except OSError:
        pass


def delete(relative_path: str | None) -> None:
    if not relative_path:
        return

    if cloudinary_enabled():
        try:
            import cloudinary.uploader

            _configure_cloudinary()

            cloudinary.uploader.destroy(
                _public_id(relative_path),
                resource_type="image",
                type="authenticated",
                invalidate=True,
            )
        except Exception:
            pass
        return

    try:
        resolve(relative_path).unlink(missing_ok=True)
    except (StorageError, OSError):
        pass
