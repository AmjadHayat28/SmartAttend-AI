"""Private file storage for uploaded images.

- Files live under settings.UPLOAD_DIR (outside the frontend; never served statically).
- Names are random UUIDs; user-supplied filenames are never used.
- Only relative paths are stored in the database and they are re-validated on every access,
  so a tampered path can never escape UPLOAD_DIR (path traversal).
- Writes go to a temp file first and are renamed into place, so a failed upload never leaves
  a half-written image behind.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Literal

from backend.app.core.config import settings

Area = Literal["faces", "profiles", "attendance"]

# The only shape a stored path can have — the server generates every one of them.
# Whitelisting (rather than blacklisting "..", drive letters, backslashes, …) closes every
# traversal trick on both POSIX and Windows.
_STORED_PATH = re.compile(r"^(faces|profiles|attendance)/[1-9][0-9]{0,9}/[0-9a-f]{32}\.jpg$")


class StorageError(Exception):
    pass


def _root() -> Path:
    return Path(settings.UPLOAD_DIR).resolve()


def resolve(relative_path: str) -> Path:
    """Absolute path for a stored relative path, refusing anything outside UPLOAD_DIR."""
    if not isinstance(relative_path, str) or not _STORED_PATH.fullmatch(relative_path):
        raise StorageError("Invalid stored path")
    root = _root()
    path = (root / Path(*relative_path.split("/"))).resolve()
    if not path.is_relative_to(root):
        raise StorageError("Invalid stored path")
    return path


def save(area: Area, owner_id: int, data: bytes, suffix: str = ".jpg") -> str:
    """Store bytes as <area>/<owner_id>/<uuid><suffix>; return the relative path."""
    if area not in ("faces", "profiles", "attendance") or not isinstance(owner_id, int) or owner_id <= 0 or suffix != ".jpg":
        raise StorageError("Invalid storage target")
    relative = f"{area}/{owner_id}/{uuid.uuid4().hex}{suffix}"
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
    path = resolve(relative_path)
    if not path.is_file():
        raise StorageError("File not found")
    return path.read_bytes()


def prune_dir(area: Area, owner_id: int) -> None:
    """Remove <area>/<owner_id>/ if it is empty (best effort, after a committed delete)."""
    if area not in ("faces", "profiles", "attendance") or not isinstance(owner_id, int) or owner_id <= 0:
        return
    try:
        (_root() / area / str(owner_id)).rmdir()  # only succeeds when empty
    except OSError:
        pass


def delete(relative_path: str | None) -> None:
    """Best-effort removal (called only after the database change has committed)."""
    if not relative_path:
        return
    try:
        resolve(relative_path).unlink(missing_ok=True)
    except (StorageError, OSError):
        pass
