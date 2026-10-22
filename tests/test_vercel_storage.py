"""Storage selection and startup checks without any Cloudinary/network requests."""

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.main import create_app
from backend.app.services import storage


CREDENTIALS = ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET")


@pytest.fixture(autouse=True)
def storage_environment(monkeypatch):
    for name in (*CREDENTIALS, "VERCEL", "VERCEL_ENV"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("missing", [None, *CREDENTIALS])
def test_vercel_production_refuses_missing_credentials_at_startup(monkeypatch, isolated_uploads, missing):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_ENV", "production")
    if missing is not None:
        for name in CREDENTIALS:
            if name != missing:
                monkeypatch.setenv(name, "test-credential")
    # Creating/importing the app must remain safe for Docker build tools.
    app = create_app()
    with pytest.raises(storage.StorageError, match="Vercel production requires CLOUDINARY") as exc:
        with TestClient(app):
            pytest.fail("startup must fail before accepting requests")
    assert "test-credential" not in str(exc.value)
    assert not isolated_uploads.exists()
    assert not storage.ready()


def test_cloudinary_startup_does_not_create_local_uploads(monkeypatch, isolated_uploads):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_ENV", "production")
    for name in CREDENTIALS:
        monkeypatch.setenv(name, "test-credential")
    with TestClient(create_app()) as client:
        assert client.get("/health/live").status_code == 200
        assert storage.ready()
    assert not isolated_uploads.exists()


def test_cloudinary_readiness_does_not_require_local_upload_directory(client, monkeypatch, tmp_path):
    for name in CREDENTIALS:
        monkeypatch.setenv(name, "test-credential")
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "not-created")
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["uploads"] == "ok"
    assert "test-credential" not in response.text
    assert not settings.UPLOAD_DIR.exists()


@pytest.mark.parametrize("vercel,vercel_env,environment", [
    (None, None, "development"),
    (None, None, "production"),  # self-hosted persistent disk remains supported
    ("1", "preview", "development"),
    ("1", "development", "development"),
])
def test_local_storage_fallback(monkeypatch, isolated_uploads, vercel, vercel_env, environment):
    if vercel:
        monkeypatch.setenv("VERCEL", vercel)
    if vercel_env:
        monkeypatch.setenv("VERCEL_ENV", vercel_env)
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    with TestClient(create_app()):
        assert isolated_uploads.is_dir()
        assert storage.ready()
        relative = storage.save("profiles", 1, b"local-test-photo")
        assert storage.read(relative) == b"local-test-photo"


def test_readiness_refuses_vercel_production_fallback_after_startup(client, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_ENV", "production")
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["uploads"] == "unavailable"
