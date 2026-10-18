"""Download and verify an InsightFace model pack (official GitHub release, pinned SHA-256).

    uv run python -m backend.app.scripts.download_face_models            # settings.FACE_RECOGNITION_MODEL
    uv run python -m backend.app.scripts.download_face_models buffalo_sc # a specific pack

Resumable: re-running continues an interrupted download.
"""

import sys
from pathlib import Path

from backend.app.core.config import settings
from backend.app.face_recognition.model_store import KNOWN_PACKS, ModelDownloadError, install_pack


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else settings.FACE_RECOGNITION_MODEL
    root = Path(settings.FACE_RECOGNITION_MODEL_DIR)
    print(f"Model pack: {name}  ->  {root / 'models' / name}")
    if name in KNOWN_PACKS:
        print(f"Pinned sha256: {KNOWN_PACKS[name][0]}  (~{KNOWN_PACKS[name][1]:.0f} MB)")
    try:
        install_pack(name, root, progress=lambda m: print(m, flush=True))
    except ModelDownloadError as exc:
        print(f"ERROR: {exc}")
        return 1
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
