"""FastAPI application entry point.

Run from the project root:  uv run uvicorn backend.app.main:app --reload
"""

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from backend.app.api.router import api_router
from backend.app.auth.dependencies import DbSession
from backend.app.core.config import settings
from backend.app.services import storage
from backend.app.services.image_validation import max_upload_bytes

log = logging.getLogger("smartclass.app")


def _configure_logging() -> None:
    """Make the app's own INFO/WARNING lines (model loading, fallback, recognition failures)
    visible under uvicorn, which only configures its own loggers."""
    app_log = logging.getLogger("smartclass")
    if not app_log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(process)d] %(name)s: %(message)s"))
        app_log.addHandler(handler)
        app_log.setLevel(logging.INFO)
        app_log.propagate = False


def _too_large_message() -> str:
    return f"Upload is too large. The maximum is {settings.MAX_UPLOAD_SIZE_MB:g} MB."


class UploadSizeLimit:
    """Refuse oversized multipart bodies before they are parsed or spooled to disk: up front by
    Content-Length, and by counting bytes as they arrive, so a chunked upload or a false
    Content-Length cannot get past the limit either. (Pure ASGI, so the body is never buffered.)"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        if not headers.get(b"content-type", b"").startswith(b"multipart/"):
            return await self.app(scope, receive, send)
        limit = max_upload_bytes() + 64 * 1024  # multipart framing around the file
        length = headers.get(b"content-length", b"")
        if length.isdigit() and int(length) > limit:
            response = JSONResponse({"detail": _too_large_message()}, status_code=status.HTTP_413_CONTENT_TOO_LARGE)
            return await response(scope, receive, send)
        received = 0

        async def counted_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # An HTTPException passes through FastAPI's body parsing unchanged → 413 response.
                    raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, _too_large_message())
            return message

        await self.app(scope, counted_receive, send)


@asynccontextmanager
async def lifespan(_: FastAPI):
    from backend.app.auth.rate_limit import rate_limit_backend

    log.info("SmartClass API starting (pid %s, environment=%s, login rate limit=%s)", os.getpid(),
             settings.ENVIRONMENT, rate_limit_backend())
    storage.validate_runtime_storage()
    if not storage.cloudinary_enabled():
        try:
            Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)  # /health/ready checks it
        except OSError as exc:
            log.error("Upload directory cannot be created (%s); uploads will fail", type(exc).__name__)
    if settings.FACE_RECOGNITION_ENABLED and settings.FACE_RECOGNITION_PRELOAD:
        from backend.app.face_recognition.model import preload_engine

        threading.Thread(target=preload_engine, name="face-model-preload", daemon=True).start()
    yield
    log.info("SmartClass API shutting down (pid %s)", os.getpid())


def create_app() -> FastAPI:
    _configure_logging()
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(UploadSizeLimit)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
        expose_headers=["Content-Disposition"],  # Excel report downloads carry their filename here
    )
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.exception_handler(IntegrityError)
    async def integrity_error(_: Request, __: IntegrityError) -> JSONResponse:
        # Safety net behind the services' explicit duplicate checks (e.g. a race between two
        # requests). The session is discarded by get_db; no SQL details are exposed.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "This change conflicts with existing data (duplicate or in-use record)."},
        )

    @app.exception_handler(OperationalError)
    async def database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
        # Connection refused / server gone / too many connections: say so plainly, log the detail.
        log.error("Database error on %s %s: %s", request.method, request.url.path, type(exc.orig).__name__)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "The database is temporarily unavailable. Please try again in a moment."},
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Last resort: the details go to the log, never to the user (no stack traces, no SQL).
        log.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Something went wrong on the server. Please try again; if it keeps "
                               "happening, contact the administrator."},
        )

    @app.get("/health", tags=["health"])
    @app.get("/health/live", tags=["health"])
    def health() -> dict[str, str]:
        """Liveness: the process is up and answering. Touches nothing else."""
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def ready(db: DbSession) -> JSONResponse:
        """Readiness: can this worker serve requests? 503 when the database or upload storage is
        unusable. Face recognition is reported but does not fail readiness (attendance can still
        be taken manually). Only coarse states — no hosts, paths, versions or error text."""
        checks: dict[str, str] = {}
        try:
            db.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:  # noqa: BLE001 - any failure means "not ready"
            log.error("Readiness: database check failed (%s)", type(exc).__name__)
            checks["database"] = "unavailable"
        checks["uploads"] = "ok" if storage.ready() else "unavailable"
        from backend.app.face_recognition.model import engine_status

        checks["face_recognition"] = engine_status()
        ok = checks["database"] == "ok" and checks["uploads"] == "ok"
        return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks},
                            status_code=status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE,
                            headers={"Cache-Control": "no-store"})

    return app


app = create_app()
