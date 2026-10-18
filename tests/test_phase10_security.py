"""Phase 10: authentication hardening, production configuration, safe logs and safe errors."""

import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy.exc import OperationalError

from backend.app.core.config import ConfigurationError, Settings, get_settings, settings
from backend.app.main import app
from backend.app.scripts.seed_demo import DEMO_PASSWORD
from tests.conftest import TEACHER_EMAIL

API = "/api/v1"
_PROD = {"ENVIRONMENT": "production", "JWT_SECRET_KEY": "k" * 48, "APP_TIMEZONE": "Asia/Karachi",
         "DATABASE_URL": "postgresql+psycopg2://app@db.internal:5432/smartclass",
         "CORS_ORIGINS": "https://attendance.example.edu"}


# ── Tokens ────────────────────────────────────────────────────────────────


def _unsigned_token():
    import base64
    import json

    part = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    exp = int((datetime.now(UTC) + timedelta(minutes=5)).timestamp())
    return f"{part({'alg': 'none', 'typ': 'JWT'})}.{part({'sub': '1', 'type': 'access', 'ver': 0, 'exp': exp})}."


def _token(**overrides):
    now = datetime.now(UTC)
    payload = {"sub": "1", "role": "teacher", "ver": 0, "type": "access", "iat": now,
               "exp": now + timedelta(minutes=5), **overrides}
    return jwt.encode(payload, overrides.pop("_key", settings.JWT_SECRET_KEY), algorithm=settings.JWT_ALGORITHM)


@pytest.mark.parametrize("token", [
    "not-a-jwt",
    _token(exp=datetime.now(UTC) - timedelta(seconds=1)),  # expired
    jwt.encode({"sub": "1", "type": "access", "ver": 0, "exp": datetime.now(UTC) + timedelta(minutes=5)},
               "a-different-secret-key-of-enough-length", algorithm="HS256"),  # forged
    _unsigned_token(),  # alg "none"
], ids=["garbage", "expired", "wrong-key", "alg-none"])
def test_invalid_tokens_are_401_with_a_plain_message(client, token):
    res = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401 and "Traceback" not in res.text and "jose" not in res.text.lower()


def test_refresh_token_cannot_be_used_as_access_token(client):
    client.post(f"{API}/auth/login", json={"email": TEACHER_EMAIL, "password": DEMO_PASSWORD})
    refresh_token = client.cookies.get("sc_refresh")
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {refresh_token}"}).status_code == 401


def test_suspension_and_password_reset_revoke_live_tokens_immediately(client, admin_h, ids, login):
    teacher = login(TEACHER_EMAIL)
    assert client.get(f"{API}/auth/me", headers=teacher).status_code == 200
    assert client.patch(f"{API}/accounts/{ids['teacher_user']}/status", headers=admin_h,
                        json={"status": "suspended", "reason": "Left the institution"}).status_code == 200
    assert client.get(f"{API}/auth/me", headers=teacher).status_code in (401, 403)
    blocked = client.post(f"{API}/auth/login", json={"email": TEACHER_EMAIL, "password": DEMO_PASSWORD})
    assert blocked.status_code == 403
    assert client.patch(f"{API}/accounts/{ids['teacher_user']}/status", headers=admin_h,
                        json={"status": "active"}).status_code == 200
    teacher = login(TEACHER_EMAIL)
    assert client.post(f"{API}/accounts/{ids['teacher_user']}/reset-password", headers=admin_h,
                       json={"new_password": "Fresh@Pass123"}).status_code == 200
    assert client.get(f"{API}/auth/me", headers=teacher).status_code == 401  # old token is dead
    assert client.post(f"{API}/auth/login", json={"email": TEACHER_EMAIL, "password": DEMO_PASSWORD}).status_code == 401
    assert client.post(f"{API}/auth/login", json={"email": TEACHER_EMAIL, "password": "Fresh@Pass123"}).status_code == 200


def test_passwords_are_bcrypt_hashed_and_never_returned(client, db_session):
    from sqlalchemy import select

    from backend.app.models import User

    with db_session() as db:
        stored = db.scalar(select(User.password_hash).where(User.email == TEACHER_EMAIL))
    assert stored.startswith("$2") and DEMO_PASSWORD not in stored
    me = client.post(f"{API}/auth/login", json={"email": TEACHER_EMAIL, "password": DEMO_PASSWORD}).json()
    profile = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {me['access_token']}"}).text
    assert "password" not in profile.lower() and "$2" not in profile


def test_login_failures_are_logged_without_passwords_or_tokens(client, caplog):
    with caplog.at_level(logging.INFO, logger="smartclass"):
        client.post(f"{API}/auth/login", json={"email": TEACHER_EMAIL, "password": "Wrong-Password-123"})
        ok = client.post(f"{API}/auth/login", json={"email": TEACHER_EMAIL, "password": DEMO_PASSWORD}).json()
        ok["refresh_token"] = client.cookies.get("sc_refresh")
    text = caplog.text
    assert "login failed" in text and TEACHER_EMAIL in text and "auth.login" in text
    assert "Wrong-Password-123" not in text and DEMO_PASSWORD not in text
    assert ok["access_token"] not in text and ok["refresh_token"] not in text


def test_rate_limited_login_is_logged(client, caplog):
    with caplog.at_level(logging.WARNING, logger="smartclass.auth"):
        codes = [client.post(f"{API}/auth/login", json={"email": TEACHER_EMAIL, "password": "nope-nope-1"}).status_code
                 for _ in range(settings.LOGIN_RATE_LIMIT_ATTEMPTS + 1)]
    assert codes[-1] == 429 and "rate limit" in caplog.text


# ── Production configuration ──────────────────────────────────────────────


def test_production_settings_are_accepted_when_complete():
    s = Settings(_env_file=None, **_PROD)
    assert s.CORS_ORIGINS == ["https://attendance.example.edu"]


@pytest.mark.parametrize("override,problem", [
    ({"JWT_SECRET_KEY": "CHANGE-ME-IN-.env"}, "JWT_SECRET_KEY"),
    ({"JWT_SECRET_KEY": "short-secret-12345"}, "JWT_SECRET_KEY"),
    ({"DEBUG": True}, "DEBUG"),
    ({"DATABASE_URL": "sqlite:///./smartclass.db"}, "DATABASE_URL"),
    ({"DATABASE_URL": "postgresql+psycopg2://smartclass:smartclass@localhost:5432/smartclass_db"}, "DATABASE_URL"),
    ({"CORS_ORIGINS": "http://localhost:5173"}, "CORS_ORIGINS"),
    ({"APP_TIMEZONE": ""}, "APP_TIMEZONE"),
])
def test_production_refuses_development_defaults(override, problem):
    with pytest.raises(ValueError) as err:
        Settings(_env_file=None, **{**_PROD, **override})
    assert problem in str(err.value)


@pytest.mark.parametrize("value", ["https://a.example.edu,https://b.example.edu",
                                   '["https://a.example.edu", "https://b.example.edu"]'])
def test_cors_origins_accept_csv_and_json_from_the_environment(monkeypatch, value):
    monkeypatch.setenv("CORS_ORIGINS", value)
    assert Settings(_env_file=None).CORS_ORIGINS == ["https://a.example.edu", "https://b.example.edu"]


@pytest.mark.parametrize("origins", ["*", "https://*.example.edu", "attendance.example.edu", "https://a.example.edu/"])
def test_wildcard_or_malformed_cors_origins_are_refused_everywhere(origins):
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings(_env_file=None, CORS_ORIGINS=origins)


def test_unknown_timezone_is_refused():
    with pytest.raises(ValueError, match="APP_TIMEZONE"):
        Settings(_env_file=None, APP_TIMEZONE="Pakistan/Lahore")


def test_configuration_errors_never_echo_secret_values(monkeypatch):
    for key, value in {**_PROD, "JWT_SECRET_KEY": "TOPSECRET-short", "DATABASE_URL": "postgresql://u:DBPASSWORD@h/x",
                       "CORS_ORIGINS": "http://localhost:5173"}.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        with pytest.raises(ConfigurationError) as err:
            get_settings()
    finally:
        get_settings.cache_clear()
    message = str(err.value)
    assert "JWT_SECRET_KEY" in message and "TOPSECRET" not in message and "DBPASSWORD" not in message


def test_default_super_admin_password_is_refused_in_production(monkeypatch, db_session):
    from backend.app.database import init_db

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "SUPERADMIN_EMAIL", "new-admin@example.edu")
    monkeypatch.setattr(settings, "SUPERADMIN_PASSWORD", "ChangeMe@123")
    monkeypatch.setattr(init_db, "SessionLocal", db_session)
    with pytest.raises(SystemExit, match="default password"):
        init_db.seed_super_admin()


def test_cors_allows_only_configured_origins(client):
    allowed = settings.CORS_ORIGINS[0]
    ok = client.options(f"{API}/auth/login", headers={"Origin": allowed, "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == allowed
    evil = client.options(f"{API}/auth/login", headers={"Origin": "https://evil.example",
                                                        "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in evil.headers


def test_api_docs_are_disabled_in_production(monkeypatch):
    from backend.app import main

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with TestClient(main.create_app()) as c:
        assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code in (200, 404)


# ── Safe errors ───────────────────────────────────────────────────────────


def test_database_outage_returns_503_with_a_plain_message(db_session, monkeypatch, caplog):
    from backend.app.database.session import get_db
    from backend.app.services import attendance_service

    def down(*_a, **_k):
        raise OperationalError("SELECT 1", {}, Exception('connection to server at "db" failed: password=xyz'))

    def override():
        with db_session() as session:
            yield session

    monkeypatch.setattr(attendance_service, "list_classes", down)
    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            token = c.post(f"{API}/auth/login", json={"email": TEACHER_EMAIL, "password": DEMO_PASSWORD}).json()
            with caplog.at_level(logging.ERROR, logger="smartclass"):
                res = c.get(f"{API}/attendance/classes", headers={"Authorization": f"Bearer {token['access_token']}"})
    finally:
        app.dependency_overrides.clear()
    assert res.status_code == 503 and "temporarily unavailable" in res.json()["detail"]
    assert "password" not in res.text and "SELECT" not in res.text and "connection" not in res.text
    assert "Database error" in caplog.text and "xyz" not in caplog.text
