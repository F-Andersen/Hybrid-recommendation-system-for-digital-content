import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.recsys.als import save_model


@pytest.fixture
def admin_settings(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, artifacts_dir=tmp_path, admin_token="test-admin-token")
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.admin.get_settings", lambda: settings)
    return settings


def test_lifespan_loads_available_domains(admin_settings, small_als):
    model, _ = small_als
    save_model(model, admin_settings.artifacts_dir, "movie")
    save_model(model, admin_settings.artifacts_dir, "book")
    with TestClient(app):
        assert set(app.state.als_models) == {"movie", "book"}


@pytest.mark.parametrize("headers", [{}, {"X-Admin-Token": "wrong"}, [(b"x-admin-token", b"\xff")]])
def test_reload_requires_valid_token(admin_settings, headers):
    with TestClient(app) as client:
        assert client.post("/admin/reload-models", headers=headers).status_code == 401


def test_reload_atomically_preserves_working_models_on_invalid_files(admin_settings, small_als):
    model, _ = small_als
    directory = admin_settings.artifacts_dir
    headers = {"X-Admin-Token": admin_settings.admin_token}
    with TestClient(app) as client:
        assert client.post("/admin/reload-models", headers=headers).status_code == 503
        save_model(model, directory, "movie")
        save_model(model, directory, "book")
        response = client.post("/admin/reload-models", headers=headers)
        assert response.status_code == 200
        assert response.json() == {"loaded": {"movie": True, "book": True}}
        previous = app.state.als_models
        (directory / "als_book.npz").write_bytes(b"corrupt")
        assert client.post("/admin/reload-models", headers=headers).status_code == 503
        assert app.state.als_models is previous
        (directory / "als_book.npz").unlink()
        (directory / "als_book_maps.json").unlink()
        assert client.post("/admin/reload-models", headers=headers).status_code == 503
        assert app.state.als_models is previous


def test_default_admin_secret_is_disabled(admin_settings):
    admin_settings.admin_token = "change-me"
    with TestClient(app) as client:
        assert client.post("/admin/reload-models", headers={
            "X-Admin-Token": "change-me",
        }).status_code == 503
