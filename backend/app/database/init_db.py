"""Apply database migrations and seed the initial super admin.

Run with:  uv run python -m backend.app.database.init_db

Schema is managed by Alembic (backend/migrations). `Base.metadata.create_all()` is used
only by the isolated test suite.
"""

import logging

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from backend.app.auth.security import hash_password
from backend.app.core.config import PROJECT_ROOT, settings
from backend.app.database.session import SessionLocal
from backend.app.models import AccountStatus, User, UserRole

logger = logging.getLogger(__name__)


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "backend" / "migrations"))
    if database_url:
        cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return cfg


def upgrade_database(database_url: str | None = None) -> None:
    """Bring the schema to the latest migration (equivalent to `alembic upgrade head`)."""
    command.upgrade(alembic_config(database_url), "head")


def seed_super_admin() -> None:
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == settings.SUPERADMIN_EMAIL.lower()))
        if existing:
            logger.info("Super admin already exists: %s", existing.email)
            return
        from pydantic import EmailStr, TypeAdapter, ValidationError

        try:  # the same check the login form applies — otherwise the account could never sign in
            TypeAdapter(EmailStr).validate_python(settings.SUPERADMIN_EMAIL)
        except ValidationError:
            raise SystemExit(f"SUPERADMIN_EMAIL is not an address that can sign in: {settings.SUPERADMIN_EMAIL!r} "
                             "(reserved domains such as .local or .test are rejected).") from None
        if settings.ENVIRONMENT.lower() == "production" and settings.SUPERADMIN_PASSWORD == "ChangeMe@123":
            raise SystemExit("Refusing to create the super admin with the default password in production. "
                             "Set SUPERADMIN_PASSWORD in .env (change it again after the first login).")
        db.add(
            User(
                email=settings.SUPERADMIN_EMAIL.lower(),
                full_name=settings.SUPERADMIN_NAME,
                password_hash=hash_password(settings.SUPERADMIN_PASSWORD),
                role=UserRole.SUPER_ADMIN,
                status=AccountStatus.ACTIVE,
            )
        )
        db.commit()
        logger.info("Created super admin: %s", settings.SUPERADMIN_EMAIL)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    upgrade_database()
    logger.info("Database is at the latest migration.")
    seed_super_admin()


if __name__ == "__main__":
    main()
