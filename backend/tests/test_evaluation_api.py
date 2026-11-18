import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, artifacts_dir=tmp_path)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.evaluation.get_settings", lambda: settings)
    (tmp_path / "eval").mkdir()
    with TestClient(app) as test_client:
        yield test_client, tmp_path / "eval"


def test_results_missing_and_present(client):
    http, directory = client
    assert http.get("/evaluation/results").json() == {"domains": {"movie": None, "book": None}}
    (directory / "movie_latest.json").write_text(json.dumps({"domain": "movie"}), "utf-8")
    (directory / "book_latest.json").write_text("{broken", "utf-8")
    assert http.get("/evaluation/results").json() == {
        "domains": {"movie": {"domain": "movie"}, "book": None}}


def test_files_are_whitelisted(client):
    http, directory = client
    (directory / "movie_2026-11-17_ndcg10.png").write_bytes(b"\x89PNG")
    (directory / "movie_params.json").write_text("{}", "utf-8")
    response = http.get("/evaluation/files/movie_2026-11-17_ndcg10.png")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    for name in ("movie_params.json", "movie_2026-11-18.csv", "..%2Fsecret.png", "x.png"):
        assert http.get(f"/evaluation/files/{name}").status_code == 404
