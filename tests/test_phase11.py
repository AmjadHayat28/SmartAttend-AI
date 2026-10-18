"""Phase 11: refresh-token cookie, shared login rate limiting, health endpoints, deployment config."""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from backend.app.auth import rate_limit
from backend.app.core.config import Settings, settings
from backend.app.main import create_app
from backend.app.models import LoginAttempt
from backend.app.scripts.seed_demo import DEMO_PASSWORD
from tests.conftest import ON_POSTGRES, TEACHER_EMAIL

API = "/api/v1"
REFRESH = {"X-Requested-With": "SmartClass"}


def _login(client, email=TEACHER_EMAIL, password=DEMO_PASSWORD):
    return client.post(f"{API}/auth/login", json={"email": email, "password": password})


def _set_cookie_header(res) -> str:
    return next(v for k, v in res.headers.multi_items() if k.lower() == "set-cookie" and v.startswith("sc_refresh="))


# ── Refresh token: HttpOnly cookie only ───────────────────────────────────


def test_login_sets_an_httponly_strict_cookie_and_never_returns_the_refresh_token(client):
    res = _login(client)
    assert res.status_code == 200
    body = res.json()
    assert body["refresh_token"] is None and body["access_token"]
    cookie = _set_cookie_header(res).lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api/v1/auth" in cookie
    assert "max-age=604800" in cookie
    assert "secure" not in cookie.split(";")[1:].__str__()  # development: plain HTTP allowed
    token = client.cookies.get("sc_refresh")
    assert token and token not in res.text


def test_cookie_is_secure_in_production(client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_COOKIE_SECURE", True)
    assert "; secure" in _set_cookie_header(_login(client)).lower()
    monkeypatch.setattr(settings, "AUTH_COOKIE_SECURE", None)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    assert settings.refresh_cookie_secure is True


def test_refresh_with_the_cookie_needs_the_csrf_header(client):
    _login(client)
    assert client.post(f"{API}/auth/refresh").status_code == 403  # cookie alone (e.g. a forged form post)
    res = client.post(f"{API}/auth/refresh", headers=REFRESH)
    assert res.status_code == 200 and res.json()["access_token"] and res.json()["refresh_token"] is None
    assert "sc_refresh=" in _set_cookie_header(res)  # renewed
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {res.json()['access_token']}"})
    assert me.status_code == 200


def test_refresh_without_cookie_is_401(client):
    assert client.post(f"{API}/auth/refresh", headers=REFRESH).status_code == 401


def test_legacy_refresh_token_in_the_body_is_moved_onto_the_cookie(client):
    _login(client)
    legacy = client.cookies.get("sc_refresh")
    client.cookies.clear()
    res = client.post(f"{API}/auth/refresh", json={"refresh_token": legacy})
    assert res.status_code == 200 and client.cookies.get("sc_refresh")


def test_a_dead_cookie_is_removed(client):
    client.cookies.set("sc_refresh", "not-a-token", path="/api/v1/auth")
    res = client.post(f"{API}/auth/refresh", headers=REFRESH)
    deletion = _set_cookie_header(res).lower()
    assert res.status_code == 401 and "max-age=0" in deletion and "path=/api/v1/auth" in deletion


def test_logout_clears_the_cookie(client):
    _login(client)
    res = client.post(f"{API}/auth/logout")
    assert res.status_code == 204 and "max-age=0" in _set_cookie_header(res).lower()
    assert client.cookies.get("sc_refresh") is None
    assert client.post(f"{API}/auth/refresh", headers=REFRESH).status_code == 401


def test_password_change_and_suspension_kill_the_refresh_cookie(client, admin_h, ids):
    access = _login(client).json()["access_token"]
    client.post(f"{API}/auth/change-password", headers={"Authorization": f"Bearer {access}"},
                json={"current_password": DEMO_PASSWORD, "new_password": "NewPass@2026"})
    assert client.post(f"{API}/auth/refresh", headers=REFRESH).status_code == 401
    _login(client, password="NewPass@2026")
    client.patch(f"{API}/accounts/{ids['teacher_user']}/status", headers=admin_h,
                 json={"status": "suspended", "reason": "Left the institution"})
    assert client.post(f"{API}/auth/refresh", headers=REFRESH).status_code == 401


def test_cors_allows_the_refresh_header_for_configured_origins(client):
    res = client.options(f"{API}/auth/refresh", headers={
        "Origin": settings.CORS_ORIGINS[0], "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-requested-with"})
    assert res.status_code == 200 and res.headers.get("access-control-allow-credentials") == "true"
    evil = client.options(f"{API}/auth/refresh", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-requested-with"})
    assert "access-control-allow-origin" not in evil.headers


# ── Shared (database) login rate limiter ──────────────────────────────────


@pytest.fixture()
def db_limiter(monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_RATE_LIMIT_BACKEND", "database")
    assert isinstance(rate_limit.get_login_rate_limiter(), rate_limit.DatabaseRateLimiter)


def test_backend_defaults(monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_RATE_LIMIT_BACKEND", None)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    assert rate_limit.rate_limit_backend() == "memory"
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    assert rate_limit.rate_limit_backend() == "database"


def test_database_limiter_blocks_after_the_limit_and_stores_no_email(client, db_limiter, db_session):
    codes = [_login(client, password="wrong-password-1").status_code for _ in range(settings.LOGIN_RATE_LIMIT_ATTEMPTS)]
    assert codes == [401] * settings.LOGIN_RATE_LIMIT_ATTEMPTS
    blocked = _login(client)  # even the right password waits
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0
    with db_session() as db:
        rows = db.scalars(select(LoginAttempt)).all()
    assert len(rows) == settings.LOGIN_RATE_LIMIT_ATTEMPTS
    assert all(len(r.key_hash) == 64 and "@" not in r.key_hash for r in rows)


def test_counts_are_shared_between_workers(db_session, db_limiter):
    """Two separate app instances (= two uvicorn workers) on one database share one count."""
    from backend.app.database.session import get_db

    def override():
        with db_session() as session:
            yield session

    workers = [create_app(), create_app()]
    for app_ in workers:
        app_.dependency_overrides[get_db] = override
    with TestClient(workers[0]) as w1, TestClient(workers[1]) as w2:
        codes = [_login((w1, w2)[i % 2], password="wrong-password-1").status_code
                 for i in range(settings.LOGIN_RATE_LIMIT_ATTEMPTS)]
        assert codes == [401] * settings.LOGIN_RATE_LIMIT_ATTEMPTS
        assert _login(w1).status_code == 429 and _login(w2).status_code == 429


def test_success_resets_and_old_attempts_expire(client, db_limiter, db_session):
    for _ in range(settings.LOGIN_RATE_LIMIT_ATTEMPTS - 1):
        _login(client, password="wrong-password-1")
    assert _login(client).status_code == 200
    with db_session() as db:
        assert db.scalar(select(func.count(LoginAttempt.id))) == 0
        old = datetime.now(UTC) - timedelta(seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS + 5)
        key = rate_limit.DatabaseRateLimiter._hash(f"testclient:{TEACHER_EMAIL}")
        db.add_all([LoginAttempt(key_hash=key, attempted_at=old) for _ in range(10)])
        db.commit()
    assert _login(client).status_code == 200  # expired attempts do not count


@pytest.mark.skipif(not ON_POSTGRES, reason="advisory locks are PostgreSQL-only")
def test_parallel_attempts_on_postgres_cannot_exceed_the_limit(client, db_limiter, db_session):
    start = threading.Barrier(10)
    codes = []

    def attempt():
        start.wait()
        codes.append(_login(client, password="wrong-password-1").status_code)

    threads = [threading.Thread(target=attempt) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert codes.count(401) == settings.LOGIN_RATE_LIMIT_ATTEMPTS and codes.count(429) == 10 - codes.count(401)


# ── Health ────────────────────────────────────────────────────────────────


def test_liveness(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health").json() == {"status": "ok"}


def test_readiness_reports_coarse_states_only(client):
    res = client.get("/health/ready")
    assert res.status_code == 200 and res.json()["status"] == "ready"
    assert res.json()["checks"] == {"database": "ok", "uploads": "ok", "face_recognition": "ready"}
    assert res.headers["cache-control"] == "no-store"
    text = res.text.lower()
    assert "postgres" not in text and "sqlite" not in text and str(settings.UPLOAD_DIR).lower() not in text


def test_readiness_is_503_when_the_database_is_down(client):
    from backend.app.database.session import get_db

    class DownSession:
        def execute(self, *_a, **_k):
            raise OperationalError("SELECT 1", {}, Exception("connection refused password=secret"))

    client.app.dependency_overrides[get_db] = lambda: DownSession()
    res = client.get("/health/ready")
    assert res.status_code == 503 and res.json()["checks"]["database"] == "unavailable"
    assert "secret" not in res.text and "refused" not in res.text


def test_readiness_is_503_without_writable_uploads(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "missing" / "uploads")
    res = client.get("/health/ready")
    assert res.status_code == 503 and res.json()["checks"]["uploads"] == "unavailable"


# ── Deployment configuration ──────────────────────────────────────────────


_PROD = {"ENVIRONMENT": "production", "JWT_SECRET_KEY": "k" * 48, "APP_TIMEZONE": "Asia/Karachi",
         "DATABASE_URL": "postgresql+psycopg2://app@127.0.0.1:5432/smartclass"}


def test_env_file_can_be_chosen_with_smartclass_env_file(monkeypatch, tmp_path):
    from backend.app.core import config

    env = tmp_path / "production.env"
    env.write_text("APP_NAME=From the production env file\nDB_POOL_SIZE=7\n", encoding="utf-8")
    monkeypatch.delenv("SMARTCLASS_ENV_FILE", raising=False)
    assert config.env_file_path() == config.PROJECT_ROOT / ".env"
    monkeypatch.setenv("SMARTCLASS_ENV_FILE", str(env))
    assert config.env_file_path() == env
    chosen = Settings(_env_file=config.env_file_path())
    assert chosen.APP_NAME == "From the production env file" and chosen.DB_POOL_SIZE == 7


@pytest.mark.parametrize("origins,ok", [
    ("https://localhost", True),  # a deliberate local HTTPS deployment
    ("https://attendance.example.edu", True),
    ("http://attendance.example.edu", False),  # production origins must be HTTPS
    ("http://localhost:5173", False),
    ("https://attendance.example.edu,http://127.0.0.1:5173", False),
])
def test_production_cors_requires_https_origins(origins, ok):
    if ok:
        assert Settings(_env_file=None, CORS_ORIGINS=origins, **_PROD).CORS_ORIGINS
    else:
        with pytest.raises(ValueError, match="CORS_ORIGINS"):
            Settings(_env_file=None, CORS_ORIGINS=origins, **_PROD)


def test_production_refuses_an_insecure_refresh_cookie():
    with pytest.raises(ValueError, match="AUTH_COOKIE_SECURE"):
        Settings(_env_file=None, CORS_ORIGINS="https://localhost", AUTH_COOKIE_SECURE=False, **_PROD)


def test_postgres_engine_gets_pool_and_connect_timeouts(monkeypatch):
    from backend.app.database import session

    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+psycopg2://u@127.0.0.1/db")
    opts = session._engine_options()
    assert opts["pool_pre_ping"] and opts["pool_size"] == settings.DB_POOL_SIZE
    assert opts["pool_recycle"] == settings.DB_POOL_RECYCLE and opts["connect_args"]["connect_timeout"] == 5
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///x.db")
    assert "pool_size" not in session._engine_options()


@pytest.mark.parametrize("email", ["admin@smartclass.local", "admin@school.test", "not-an-email"])
def test_init_db_refuses_a_super_admin_email_that_could_never_sign_in(monkeypatch, db_session, email):
    from backend.app.database import init_db

    monkeypatch.setattr(settings, "SUPERADMIN_EMAIL", email)
    monkeypatch.setattr(init_db, "SessionLocal", db_session)
    with pytest.raises(SystemExit, match="cannot|can sign in"):
        init_db.seed_super_admin()
