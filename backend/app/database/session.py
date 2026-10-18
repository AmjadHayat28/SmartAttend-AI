"""Engine and session factory."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import settings

def _engine_options() -> dict:
    options: dict = {"echo": settings.DB_ECHO, "pool_pre_ping": True}  # pre-ping: survive DB restarts
    if settings.DATABASE_URL.startswith("postgresql"):
        options.update(pool_size=settings.DB_POOL_SIZE, max_overflow=settings.DB_MAX_OVERFLOW,
                       pool_timeout=settings.DB_POOL_TIMEOUT, pool_recycle=settings.DB_POOL_RECYCLE,
                       connect_args={"connect_timeout": settings.DB_CONNECT_TIMEOUT,
                                     "application_name": "smartclass"})
    return options


engine = create_engine(settings.DATABASE_URL, **_engine_options())
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
