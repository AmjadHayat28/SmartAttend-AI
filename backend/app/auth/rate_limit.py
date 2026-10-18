"""Sliding-window rate limiting of failed logins (per client IP + email).

Two interchangeable backends (settings.LOGIN_RATE_LIMIT_BACKEND):

- "database" (production default): failed attempts are rows in `login_attempts`, so every uvicorn
  worker (and every server sharing the database) sees the same counts, and a restart does not
  reset them. Keys are stored as SHA-256 hashes, never as plain emails. On PostgreSQL a
  per-key advisory lock serialises concurrent attempts, so parallel requests spread over several
  workers cannot slip past the limit together.
- "memory" (development default): an in-process dict. Correct for ONE process only — with
  several workers each one counts separately.
"""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from threading import Lock

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from backend.app.core.config import settings


class SlidingWindowRateLimiter:
    """In-memory backend. `db` arguments are accepted (same interface) and ignored."""

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()
        return hits

    def retry_after(self, key: str, db: Session | None = None) -> int:
        """Seconds until another attempt is allowed (0 = allowed now)."""
        with self._lock:
            now = time.monotonic()
            hits = self._prune(key, now)
            if len(hits) < self.max_attempts:
                return 0
            return max(1, int(self.window_seconds - (now - hits[0])))

    def record_failure(self, key: str, db: Session | None = None) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune(key, now).append(now)

    def reset(self, key: str | None = None, db: Session | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


class DatabaseRateLimiter:
    """Shared backend: one row per failed attempt in `login_attempts`. Commits its own writes
    (callers invoke it at points where nothing else is pending in the session)."""

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds

    @staticmethod
    def _hash(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def retry_after(self, key: str, db: Session) -> int:
        from backend.app.models import LoginAttempt

        digest = self._hash(key)
        if db.get_bind().dialect.name == "postgresql":
            # Held until this request's transaction ends: concurrent attempts for the same key
            # (on any worker) are counted one after another, never in parallel.
            db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": int(digest[:15], 16)})
        now = datetime.now(UTC)
        since = now - timedelta(seconds=self.window_seconds)
        count, oldest = db.execute(
            select(func.count(LoginAttempt.id), func.min(LoginAttempt.attempted_at))
            .where(LoginAttempt.key_hash == digest, LoginAttempt.attempted_at > since)).one()
        if count < self.max_attempts:
            return 0
        oldest = oldest.replace(tzinfo=UTC) if oldest.tzinfo is None else oldest
        return max(1, int(self.window_seconds - (now - oldest).total_seconds()))

    def record_failure(self, key: str, db: Session) -> None:
        from backend.app.models import LoginAttempt

        now = datetime.now(UTC)
        db.add(LoginAttempt(key_hash=self._hash(key), attempted_at=now))
        # Housekeeping: attempts older than the window can never matter again.
        db.execute(delete(LoginAttempt).where(LoginAttempt.attempted_at < now - timedelta(seconds=self.window_seconds)))
        db.commit()

    def reset(self, key: str | None = None, db: Session | None = None) -> None:
        from backend.app.models import LoginAttempt

        if db is None:
            return
        stmt = delete(LoginAttempt)
        if key is not None:
            stmt = stmt.where(LoginAttempt.key_hash == self._hash(key))
        db.execute(stmt)
        db.commit()


def rate_limit_backend() -> str:
    if settings.LOGIN_RATE_LIMIT_BACKEND:
        return settings.LOGIN_RATE_LIMIT_BACKEND
    return "database" if settings.ENVIRONMENT.lower() == "production" else "memory"


_memory_limiter = SlidingWindowRateLimiter(settings.LOGIN_RATE_LIMIT_ATTEMPTS, settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS)


def get_login_rate_limiter() -> SlidingWindowRateLimiter | DatabaseRateLimiter:
    """The configured backend (read per call, so tests and settings changes apply)."""
    if rate_limit_backend() == "database":
        return DatabaseRateLimiter(settings.LOGIN_RATE_LIMIT_ATTEMPTS, settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS)
    return _memory_limiter


# Backwards-compatible name for the in-memory instance (tests reset it between tests).
login_rate_limiter = _memory_limiter
