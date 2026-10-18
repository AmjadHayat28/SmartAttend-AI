"""Verified download of InsightFace model packs.

Packs come from the official InsightFace GitHub release "model-zoo"
(https://github.com/deepinsight/insightface/releases/tag/model-zoo). Each zip is checked against
the SHA-256 digest GitHub publishes for that release asset (pinned below) before extraction.
After extraction the SHA-256 of every .onnx file is recorded in SHA256SUMS and re-checked on
every load, so a modified model file is refused.

InsightFace's own auto-download is never used: it does not verify downloads.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

RELEASE_URL = "https://github.com/deepinsight/insightface/releases/download/model-zoo/{name}.zip"

# name → (sha256 of the zip as published by GitHub for the release asset, approx. size in MB)
KNOWN_PACKS: dict[str, tuple[str, float]] = {
    "buffalo_l": ("80ffe37d8a5940d59a7384c201a2a38d4741f2f3c51eef46ebb28218a7b0ca2f", 288.6),
    "buffalo_s": ("d85a87f503f691807cd8bb97128bdf7a0660326cd9cd02657127fa978bab8b5e", 127.6),
    "buffalo_sc": ("57d31b56b6ffa911c8a73cfc1707c73cab76efe7f13b675a05223bf42de47c72", 15.0),
}


class ModelDownloadError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pack_dir(root: Path, name: str) -> Path:
    return root / "models" / name


_CONTENT_RANGE = re.compile(r"bytes\s+(?:(\d+)-\d+|\*)/(\d+|\*)")


def _content_range(value: str | None) -> tuple[int | None, int | None]:
    """'bytes 100-199/500' → (100, 500); 'bytes */500' → (None, 500)."""
    m = _CONTENT_RANGE.match(value or "")
    if not m:
        return None, None
    start = int(m.group(1)) if m.group(1) else None
    total = int(m.group(2)) if m.group(2) != "*" else None
    return start, total


def _set_aside(partial: Path, progress) -> None:
    """Keep an unusable partial for inspection instead of deleting it, and start over."""
    corrupt = partial.with_name(f"{partial.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
    partial.replace(corrupt)
    progress(f"  partial download is not a valid prefix of the file; set aside as {corrupt.name}, restarting")


def _download(url: str, target: Path, retries: int = 40, progress=print) -> None:
    """Resumable download (HTTP Range) with retries — slow links are expected.

    Safety: one writer at a time (a .lock file next to the .part), a resume is accepted only
    when the server's Content-Range starts exactly where the partial file ends, and a partial
    larger than the whole file is set aside (renamed, never silently appended to).
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    lock = partial.with_name(partial.name + ".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ModelDownloadError(f"Another download of {target.name} seems to be running ({lock}). "
                                 "If none is, delete the .lock file and retry.") from None
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    try:
        for attempt in range(1, retries + 1):
            have = partial.stat().st_size if partial.exists() else 0
            request = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
            try:
                try:
                    response = urllib.request.urlopen(request, timeout=120)
                except urllib.error.HTTPError as exc:
                    if exc.code != 416 or not have:
                        raise
                    # Nothing left to send from `have`: complete, or longer than the real file.
                    _, total = _content_range(exc.headers.get("Content-Range"))
                    if total is not None and have == total:
                        partial.replace(target)
                        return
                    _set_aside(partial, progress)
                    continue
                with response, open(partial, "ab" if have else "wb") as out:
                    total = int(response.headers.get("Content-Length") or 0)
                    if have and response.status == 206:
                        start, full = _content_range(response.headers.get("Content-Range"))
                        if start is not None and start != have:  # not a continuation: start over
                            out.truncate(0)
                            out.close()
                            raise ConnectionError(f"server resumed at byte {start}, expected {have}")
                        if full is not None and have > full:
                            raise ConnectionError("partial larger than the file")
                        total += have
                    elif have:  # server ignored Range and sent the whole file: start over
                        out.truncate(0)
                    last = time.monotonic()
                    while chunk := response.read(1 << 20):
                        out.write(chunk)
                        if time.monotonic() - last > 15:
                            last = time.monotonic()
                            progress(f"  {out.tell() / 1e6:.1f} / {total / 1e6:.1f} MB")
                    received = out.tell()
                # A server may close the connection early without an error: keep the partial
                # file and resume rather than treating a truncated download as complete.
                if total and received < total:
                    raise ConnectionError(f"connection closed early at {received / 1e6:.1f} / {total / 1e6:.1f} MB")
                if total and received > total:
                    _set_aside(partial, progress)
                    continue
                partial.replace(target)
                return
            except OSError as exc:
                progress(f"  attempt {attempt} interrupted ({type(exc).__name__}: {exc}); resuming...")
                time.sleep(min(30, 2 * attempt))
        raise ModelDownloadError(f"Download failed after {retries} attempts: {url}")
    finally:
        lock.unlink(missing_ok=True)


def record_checksums(model_dir: Path) -> dict[str, str]:
    sums = {f.name: sha256_file(f) for f in sorted(model_dir.glob("*.onnx"))}
    (model_dir / "SHA256SUMS").write_text("".join(f"{d}  {n}\n" for n, d in sums.items()))
    return sums


def verify_installed(model_dir: Path) -> dict[str, str]:
    """SHA-256 of each model file, checked against SHA256SUMS written at install time."""
    manifest = model_dir / "SHA256SUMS"
    files = sorted(model_dir.glob("*.onnx"))
    if not files or not manifest.exists():
        raise ModelDownloadError(f"Model pack in {model_dir.name} is incomplete or was not installed by the "
                                 "download script.")
    expected = {}
    for line in manifest.read_text().splitlines():
        if line.strip():
            digest, name = line.split(None, 1)
            expected[name.strip()] = digest
    actual = {f.name: sha256_file(f) for f in files}
    bad = sorted(n for n in actual if expected.get(n) != actual[n])
    if bad:
        raise ModelDownloadError(f"Model file(s) failed the integrity check: {', '.join(bad)}")
    return actual


def install_pack(name: str, root: Path, progress=print) -> Path:
    """Download (if needed), verify against the pinned digest, extract, record checksums."""
    if name not in KNOWN_PACKS:
        raise ModelDownloadError(f"Unknown model pack '{name}'. Known: {', '.join(KNOWN_PACKS)}")
    expected, size_mb = KNOWN_PACKS[name]
    target_dir = pack_dir(root, name)
    if (target_dir / "SHA256SUMS").exists():
        verify_installed(target_dir)
        progress(f"{name} already installed and verified.")
        return target_dir
    zip_path = root / "models" / f"{name}.zip"
    if not zip_path.exists() or sha256_file(zip_path) != expected:
        progress(f"Downloading {name} (~{size_mb:.0f} MB) from {RELEASE_URL.format(name=name)}")
        _download(RELEASE_URL.format(name=name), zip_path, progress=progress)
    actual = sha256_file(zip_path)
    if actual != expected:
        zip_path.unlink(missing_ok=True)
        raise ModelDownloadError(f"{name}.zip failed verification (sha256 {actual[:16]}... != pinned {expected[:16]}...)")
    progress(f"Verified {name}.zip (sha256 {expected[:16]}...). Extracting...")
    tmp = target_dir.with_name(target_dir.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():  # refuse path traversal inside the archive
            if Path(member).is_absolute() or ".." in Path(member).parts:
                raise ModelDownloadError(f"Unsafe path in archive: {member}")
        zf.extractall(tmp)
    # Some packs nest the files in a folder named after the pack.
    nested = tmp / name
    source = nested if nested.is_dir() and not list(tmp.glob("*.onnx")) else tmp
    shutil.rmtree(target_dir, ignore_errors=True)
    shutil.move(str(source), str(target_dir))
    shutil.rmtree(tmp, ignore_errors=True)
    sums = record_checksums(target_dir)
    progress(f"Installed {name}: {', '.join(sums)}")
    return target_dir
