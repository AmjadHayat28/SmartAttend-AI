"""Application settings, loaded from environment variables / .env."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Development defaults that must never reach production (see Settings.production_safety).
_DEV_DATABASE_URL = "postgresql+psycopg2://smartclass:smartclass@localhost:5432/smartclass_db"
_DEV_SECRETS = {"CHANGE-ME-IN-.env", "replace-with-a-long-random-secret"}
_DEV_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",  # get_settings() may choose another one (env_file_path)
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    APP_NAME: str = "SmartClass AI Attendance"
    ENVIRONMENT: str = "development"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = _DEV_DATABASE_URL
    DB_ECHO: bool = False
    # Connection pool (PostgreSQL). Per worker process: at most POOL_SIZE + MAX_OVERFLOW connections.
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=50)
    DB_MAX_OVERFLOW: int = Field(default=5, ge=0, le=50)
    DB_POOL_TIMEOUT: int = Field(default=10, ge=1)  # seconds to wait for a free pooled connection
    DB_POOL_RECYCLE: int = Field(default=1800, ge=60)  # replace connections older than this (seconds)
    DB_CONNECT_TIMEOUT: int = Field(default=5, ge=1)  # seconds; a down database fails fast (→ 503)

    # Security / JWT
    JWT_SECRET_KEY: str = Field(default="CHANGE-ME-IN-.env", min_length=16)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # The refresh token lives only in an HttpOnly cookie scoped to {API_V1_PREFIX}/auth (never in
    # JSON or browser storage). Secure: None = only in production (HTTPS). SameSite=strict: the
    # browser never sends it with a request started by another site.
    AUTH_REFRESH_COOKIE: str = "sc_refresh"
    AUTH_COOKIE_SECURE: bool | None = None
    AUTH_COOKIE_SAMESITE: Literal["strict", "lax"] = "strict"
    PASSWORD_MIN_LENGTH: int = 8
    # bcrypt cost factor. Keep 12+ in production; the test suite lowers it for speed.
    BCRYPT_ROUNDS: int = Field(default=12, ge=4, le=16)

    # Login rate limiting (per client IP + email)
    LOGIN_RATE_LIMIT_ATTEMPTS: int = 5
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 300
    # "database": shared by all workers/servers and survives restarts (production default).
    # "memory": per process — only correct with ONE worker (development default). Empty = default.
    LOGIN_RATE_LIMIT_BACKEND: Literal["database", "memory"] | None = None

    # CORS
    # Comma-separated ("https://a.edu,https://b.edu") or a JSON list. NoDecode: let split_csv parse it.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Uploads (stored outside the frontend, served only through authorised API endpoints)
    UPLOAD_DIR: Path = PROJECT_ROOT / "uploads"
    MAX_UPLOAD_SIZE_MB: float = Field(default=8, gt=0)
    ALLOWED_IMAGE_TYPES: Annotated[list[str], NoDecode] = ["image/jpeg", "image/png"]

    # Image validation (profile + face-enrollment photos)
    IMAGE_MIN_DIMENSION: int = 200  # shorter side below this → rejected ("too small")
    IMAGE_RECOMMENDED_MIN_DIMENSION: int = 480  # below this → warning
    IMAGE_MAX_PIXELS: int = 40_000_000  # decompression-bomb guard
    IMAGE_STORE_MAX_DIMENSION: int = 1600  # stored copies are downscaled to this longest side
    IMAGE_BLANK_STDDEV: float = 5.0  # grey-level std-dev below this → "appears blank"

    # Face enrollment (Phase 4: detection + quality only — no embeddings)
    FACE_DETECTION_SCORE: float = Field(default=0.7, ge=0.1, le=0.99)
    FACE_MIN_SIZE_RATIO: float = 0.06  # detections smaller than this share of the image are ignored
    FACE_RECOMMENDED_SIZE_RATIO: float = 0.2  # face smaller than this → warning "move closer"
    FACE_BLUR_FAIL: float = 8.0  # Laplacian variance of the normalised face crop (lenient defaults)
    FACE_BLUR_WARN: float = 30.0
    FACE_BRIGHTNESS_FAIL_LOW: float = 35.0  # mean grey level of the face crop (0–255)
    FACE_BRIGHTNESS_WARN_LOW: float = 70.0
    FACE_BRIGHTNESS_WARN_HIGH: float = 205.0
    FACE_BRIGHTNESS_FAIL_HIGH: float = 235.0
    FACE_MAX_PHOTOS: int = Field(default=5, ge=3, le=10)

    # Short-lived token that lets a newly registered (pending) student upload their photos
    ONBOARDING_TOKEN_EXPIRE_MINUTES: int = 60

    # Attendance
    # The one low-attendance threshold (%): student warnings, student dashboard and teacher reports.
    # STUDENT_LOW_ATTENDANCE_THRESHOLD is still read as a deprecated fallback name for older .env
    # files; LOW_ATTENDANCE_THRESHOLD wins when both are set.
    LOW_ATTENDANCE_THRESHOLD: float = Field(
        default=75.0, ge=0.0, le=100.0,
        validation_alias=AliasChoices("LOW_ATTENDANCE_THRESHOLD", "STUDENT_LOW_ATTENDANCE_THRESHOLD"),
    )
    # Percentage policy (applies to FINALIZED sessions only):
    #   attended  = present + late × ATTENDANCE_LATE_WEIGHT (+ excused if policy is "present")
    #   conducted = all finalized records, minus excused if policy is "exclude"
    ATTENDANCE_LATE_WEIGHT: float = Field(default=1.0, ge=0.0, le=1.0)
    ATTENDANCE_EXCUSED_POLICY: Literal["exclude", "present", "absent"] = "exclude"
    # Session-taking rules for teachers
    ATTENDANCE_MAX_SESSIONS_PER_DAY: int = Field(default=8, ge=1, le=20)
    ATTENDANCE_MAX_BACKDATE_DAYS: int = Field(default=14, ge=0)  # how far back a teacher may start a session
    ATTENDANCE_TEACHER_CORRECTION_HOURS: int = Field(default=24, ge=0)  # 0 = locked as soon as it is finalized
    ATTENDANCE_MAX_PHOTOS: int = Field(default=5, ge=1, le=20)
    ATTENDANCE_PHOTO_MIN_DIMENSION: int = 480  # classroom photos must be at least this on the short side
    ATTENDANCE_PHOTO_MAX_DIMENSION: int = 2560  # stored copies are downscaled to this longest side
    # Long side ÷ short side above this is not a classroom photo (a strip would be downscaled to
    # a few pixels high). Phone panoramas are ~3–5.
    ATTENDANCE_PHOTO_MAX_ASPECT_RATIO: float = Field(default=6.0, ge=1.0)
    # Timezone used for "today" when validating attendance dates (IANA name). Empty = server local time.
    APP_TIMEZONE: str = ""

    # Face recognition (Phase 6) — assists the teacher; never finalizes attendance.
    FACE_RECOGNITION_ENABLED: bool = True
    FACE_RECOGNITION_MODEL: str = "buffalo_l"  # InsightFace model pack (SCRFD detector + ArcFace)
    FACE_RECOGNITION_MODEL_DIR: Path = PROJECT_ROOT / "models_cache" / "insightface"  # git-ignored
    # Never download inside a teacher's request by default (a pack is 15–290 MB). Install it ahead of
    # time with: uv run python -m backend.app.scripts.download_face_models
    FACE_RECOGNITION_ALLOW_DOWNLOAD: bool = False
    FACE_RECOGNITION_DET_SIZE: int = Field(default=1024, ge=320, le=2048)  # classroom detector input
    # Fallback pack when FACE_RECOGNITION_MODEL cannot be loaded ("" = no fallback). The pack
    # actually used is recorded on every recognition run.
    FACE_RECOGNITION_FALLBACK_MODEL: str = "buffalo_sc"
    # Load the model in a background thread at startup so the first teacher does not wait for it
    # (~9 s for buffalo_l incl. checksum verification). Requests arriving meanwhile wait for it.
    FACE_RECOGNITION_PRELOAD: bool = True
    # After a failed load, refuse quickly for this long instead of re-reading and re-hashing the
    # model files on every request.
    FACE_RECOGNITION_RETRY_SECONDS: int = Field(default=60, ge=0)
    # A run that takes longer than this is stopped between photos (attendance unchanged).
    FACE_RECOGNITION_TIMEOUT_SECONDS: int = Field(default=240, ge=1)
    # FACE DETECTION confidence (is this a face?) — independent of FACE_MATCH_* (is it this student?).
    FACE_RECOGNITION_MIN_DET_SCORE: float = Field(default=0.5, ge=0.1, le=0.99)
    # Group photos: overlapping native-resolution tiles for large photos (small/distant faces),
    # automatic sideways-photo orientation, and the IoU used to merge duplicate boxes.
    FACE_RECOGNITION_TILING: bool = True
    FACE_RECOGNITION_TILE_SIZE: int = Field(default=1024, ge=320, le=2048)
    FACE_RECOGNITION_TILE_OVERLAP: float = Field(default=0.25, ge=0.1, le=0.5)
    FACE_RECOGNITION_AUTO_ORIENT: bool = True
    FACE_RECOGNITION_NMS_IOU: float = Field(default=0.4, ge=0.1, le=0.9)
    FACE_RECOGNITION_MIN_FACE_PX: int = Field(default=20, ge=8)  # ignore faces smaller than this
    # Matching thresholds (cosine similarity of ArcFace embeddings). Checked in Phase 8 on a small
    # labelled set only — re-check with backend/app/scripts/benchmark_recognition.py before changing.
    FACE_MATCH_CONFIDENT: float = Field(default=0.50, ge=0.0, le=1.0)
    FACE_MATCH_LOW: float = Field(default=0.35, ge=0.0, le=1.0)
    FACE_MATCH_AMBIGUITY_MARGIN: float = Field(default=0.06, ge=0.0, le=1.0)
    # With ≥3 approved photos, an enrollment embedding whose mean similarity to the student's
    # other photos is below this is left out of matching (likely not the student / unusable).
    FACE_ENROLLMENT_MIN_CONSISTENCY: float = Field(default=0.2, ge=-1.0, le=1.0)

    # Initial super admin (used by the seed script only)
    SUPERADMIN_EMAIL: str = "admin@smartclass.edu"
    SUPERADMIN_PASSWORD: str = "ChangeMe@123"
    SUPERADMIN_NAME: str = "System Administrator"

    @field_validator("CORS_ORIGINS", "ALLOWED_IMAGE_TYPES", mode="before")
    @classmethod
    def split_csv(cls, value):
        if isinstance(value, str):
            if value.strip().startswith("["):
                import json

                return json.loads(value)
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("CORS_ORIGINS")
    @classmethod
    def explicit_origins(cls, value: list[str]) -> list[str]:
        # Credentials (the Authorization header) are allowed, so a wildcard origin is never valid.
        for origin in value:
            if origin == "*" or "*" in origin or not origin.startswith(("http://", "https://")) or origin.endswith("/"):
                raise ValueError(f"CORS_ORIGINS entries must be exact origins like https://attendance.example.edu "
                                 f"(no wildcard, no trailing slash); got {origin!r}")
        return value

    @field_validator("APP_TIMEZONE")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        if value:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError(f"APP_TIMEZONE must be an IANA timezone name such as Asia/Karachi; got {value!r}") from None
        return value

    @property
    def refresh_cookie_secure(self) -> bool:
        if self.AUTH_COOKIE_SECURE is not None:
            return self.AUTH_COOKIE_SECURE
        return self.ENVIRONMENT.lower() == "production"

    @property
    def refresh_cookie_path(self) -> str:
        return f"{self.API_V1_PREFIX}/auth"

    @model_validator(mode="after")
    def production_safety(self) -> "Settings":
        """Refuse to start in production with development defaults (fail loudly, not insecurely)."""
        if self.ENVIRONMENT.lower() != "production":
            return self
        problems = []
        if self.JWT_SECRET_KEY in _DEV_SECRETS or len(self.JWT_SECRET_KEY) < 32:
            problems.append("JWT_SECRET_KEY must be a random secret of at least 32 characters "
                            '(uv run python -c "import secrets; print(secrets.token_urlsafe(64))")')
        if self.DEBUG:
            problems.append("DEBUG must be false")
        if not self.DATABASE_URL.startswith("postgresql") or self.DATABASE_URL == _DEV_DATABASE_URL:
            problems.append("DATABASE_URL must point at the production PostgreSQL database (not SQLite, not the "
                            "development default)")
        if (not self.CORS_ORIGINS or any(not o.startswith("https://") for o in self.CORS_ORIGINS)
                or set(self.CORS_ORIGINS) & _DEV_ORIGINS):
            problems.append("CORS_ORIGINS must list the real frontend origin(s), served over https:// "
                            "(the development defaults are not allowed)")
        if self.AUTH_COOKIE_SECURE is False:
            problems.append("AUTH_COOKIE_SECURE must not be false (the refresh cookie needs HTTPS)")
        if not self.APP_TIMEZONE:
            problems.append("APP_TIMEZONE must be set (e.g. Asia/Karachi) so 'today' does not depend on the server clock")
        if problems:
            raise ValueError("Unsafe production configuration:\n  - " + "\n  - ".join(problems))
        return self


class ConfigurationError(RuntimeError):
    """Invalid settings. The message lists the problems only — never the values (they may be secrets)."""


def env_file_path() -> Path:
    """The settings file: $SMARTCLASS_ENV_FILE (e.g. a production env kept outside the repository)
    or the project's .env. Real environment variables always take precedence over the file."""
    chosen = os.environ.get("SMARTCLASS_ENV_FILE")
    return Path(chosen) if chosen else PROJECT_ROOT / ".env"


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings(_env_file=env_file_path())
    except ValidationError as exc:
        problems = "\n".join(f"- {'.'.join(map(str, e['loc'])) or 'settings'}: {e['msg']}" for e in exc.errors())
        raise ConfigurationError(f"Invalid configuration (.env / environment):\n{problems}") from None


settings = get_settings()
