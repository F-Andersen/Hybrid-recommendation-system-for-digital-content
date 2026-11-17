import pytest
from fastapi.testclient import TestClient

from app.api import health
from app.llm.client import OllamaClient, normalize_model_name
from app.main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(health, "check_db", lambda: health.DbStatus(ok=True, pgvector=True))
    monkeypatch.setattr("app.main.load_available_models", lambda _: {})
    with TestClient(app) as c:
        yield c


def _fake_models(names):
    async def list_models(self):
        return names

    return list_models


def test_normalize_model_name():
    assert normalize_model_name("bge-m3") == "bge-m3:latest"
    assert normalize_model_name("qwen3:8b") == "qwen3:8b"


def test_health_ok(client, monkeypatch):
    monkeypatch.setattr(OllamaClient, "list_models", _fake_models(["qwen3:8b", "bge-m3:latest"]))
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["ollama"]["models_missing"] == []
    assert body["als_loaded"] == {"movie": False, "book": False}


def test_health_reports_missing_models(client, monkeypatch):
    monkeypatch.setattr(OllamaClient, "list_models", _fake_models(["llama3.1:8b"]))
    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["ollama"]["ok"] is True
    assert set(body["ollama"]["models_missing"]) == {"qwen3:8b", "bge-m3"}


def test_health_ollama_down(client, monkeypatch):
    async def boom(self):
        raise ConnectionError("refused")

    monkeypatch.setattr(OllamaClient, "list_models", boom)
    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["ollama"]["ok"] is False
    assert "refused" in body["ollama"]["error"]
