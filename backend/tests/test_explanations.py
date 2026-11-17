import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select

from app.db.models import Item, LlmCache, Rating
from app.llm.client import OllamaClient
from app.llm.prompts import build_messages, response_schema
from app.llm.rerank import validate_choices
from app.services.explanations import candidate_evidence
from tests.test_user_api import register
from tests.test_user_api import user_api as user_api

UKRAINIAN = "Вам може сподобатися цей твір завдяки подібним жанрам і тематиці."


def valid_payload(numbers=range(1, 11)):
    return {"recommendations": [{"n": number, "explanation": UKRAINIAN} for number in numbers]}


def mock_chat(monkeypatch, payload=None, error=None):
    calls = []

    async def chat(self, messages, schema, model):
        calls.append({"messages": messages, "schema": schema, "model": model})
        if error is not None:
            raise error
        return payload if payload is not None else valid_payload()

    monkeypatch.setattr(OllamaClient, "chat_json", chat)
    return calls


def test_explain_cache_get_and_different_k(user_api, sessions, monkeypatch):
    client, _ = user_api
    register(client)
    before = client.get("/recommendations").json()
    assert all(row["explanation"] is None for row in before)
    calls = mock_chat(monkeypatch, valid_payload(range(30, 20, -1)))
    first = client.post("/recommendations/explain", json={"domain": "movie"})
    assert first.status_code == 200
    result = first.json()
    assert len(result) == 10 and all(row["explanation"] == UKRAINIAN for row in result)
    assert [row["item"]["id"] for row in result] == list(range(30, 20, -1))
    assert len(calls) == 1
    assert client.post("/recommendations/explain", json={"domain": "movie"}).json() == result
    assert client.get("/recommendations").json() == result
    assert client.get("/recommendations?k=5").json() == result[:5]
    full = client.get("/recommendations?k=50").json()
    assert len(full) == 40 and len({row["item"]["id"] for row in full}) == 40
    assert full[:10] == result
    assert all(row["explanation"] is None for row in full[10:])
    assert client.get("/recommendations?model=popular").json() == before
    assert len(calls) == 1
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(LlmCache)) == 1


@pytest.mark.parametrize("error", [
    ValueError("bad JSON"), httpx.ReadTimeout("timeout"), httpx.ConnectError("offline"),
    httpx.HTTPStatusError("unavailable", request=httpx.Request("POST", "http://ollama/api/chat"),
                          response=httpx.Response(503)),
])
def test_invalid_json_and_network_errors_return_uncached_hybrid(
    user_api, sessions, monkeypatch, error,
):
    client, _ = user_api
    register(client)
    before = client.get("/recommendations").json()
    calls = mock_chat(monkeypatch, error=error)
    response = client.post("/recommendations/explain", json={"domain": "movie"})
    assert response.status_code == 200 and response.json() == before
    assert len(calls) == (2 if isinstance(error, ValueError) else 1)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(LlmCache)) == 0


def test_invalid_json_is_retried_once_then_valid_answer_is_cached(user_api, monkeypatch):
    client, _ = user_api
    register(client)
    calls = []

    async def chat(self, messages, schema, model):
        calls.append(model)
        if len(calls) == 1:
            raise ValueError("invalid JSON")
        return valid_payload()

    monkeypatch.setattr(OllamaClient, "chat_json", chat)
    response = client.post("/recommendations/explain", json={})
    assert len(response.json()) == 10
    assert all(row["explanation"] == UKRAINIAN for row in response.json())
    assert len(calls) == 2


def test_invalid_numbers_duplicates_and_empty_explanations_are_filled(user_api, monkeypatch):
    client, _ = user_api
    register(client)
    payload = valid_payload([30, 30, 999, 0, -1])
    payload["recommendations"] += [
        {"n": 1, "explanation": ""}, {"n": True, "explanation": UKRAINIAN},
        {"n": "2", "explanation": UKRAINIAN}, {"n": 2, "explanation": "An English response only."},
        {"n": 3, "explanation": UKRAINIAN},
    ]
    mock_chat(monkeypatch, payload)
    result = client.post("/recommendations/explain", json={}).json()
    assert len(result) == 10 and len({row["item"]["id"] for row in result}) == 10
    assert [row["item"]["id"] for row in result[:2]] == [30, 3]
    assert sum(row["explanation"] is not None for row in result) == 2
    assert client.get("/recommendations").json() == result


def test_ratings_and_views_invalidate_cache(user_api, sessions, monkeypatch):
    client, _ = user_api
    register(client)
    calls = mock_chat(monkeypatch)
    first = client.post("/recommendations/explain", json={}).json()
    assert len(first) == 10
    for value in (9, 8):
        assert client.put("/ratings/1", json={"value": value}).status_code == 200
        assert all(row["explanation"] is None for row in client.get("/recommendations").json())
        assert len(client.post("/recommendations/explain", json={}).json()) == 10
    assert len(calls) == 3
    client.get("/items/2")
    assert len(client.post("/recommendations/explain", json={}).json()) == 10
    assert len(calls) == 4
    client.delete("/ratings/1")
    assert len(client.post("/recommendations/explain", json={}).json()) == 10
    assert len(calls) == 5
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(LlmCache)) == 1


def test_user_domain_model_and_prompt_version_isolation(user_api, monkeypatch):
    client, settings = user_api
    register(client)
    calls = mock_chat(monkeypatch)
    assert len(client.post("/recommendations/explain", json={}).json()) == 10
    book = client.post("/recommendations/explain", json={"domain": "book"}).json()
    assert len(book) == 1 and book[0]["explanation"] == UKRAINIAN
    settings.llm_model = "qwen3:changed"
    assert len(client.post("/recommendations/explain", json={}).json()) == 10
    monkeypatch.setattr("app.services.explanations.PROMPT_VERSION", "next-version")
    assert len(client.post("/recommendations/explain", json={}).json()) == 10
    register(client, "second@example.com")
    assert all(row["explanation"] is None for row in client.get("/recommendations").json())
    assert len(client.post("/recommendations/explain", json={}).json()) == 10
    assert len(calls) == 5


def test_changed_profile_during_generation_does_not_save_stale_cache(
    user_api, sessions, monkeypatch,
):
    client, _ = user_api
    profile, _ = register(client)

    async def chat(self, messages, schema, model):
        with sessions.begin() as session:
            session.add(Rating(user_id=profile["id"], item_id=1, value=9,
                               implicit=False, rated_at=datetime.now(UTC)))
        return valid_payload()

    monkeypatch.setattr(OllamaClient, "chat_json", chat)
    result = client.post("/recommendations/explain", json={}).json()
    assert len(result) == 10 and all(row["explanation"] is None for row in result)
    assert 1 not in {row["item"]["id"] for row in result}
    assert all(row["explanation"] is None for row in client.get("/recommendations").json())
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(LlmCache)) == 0


def test_corrupted_cache_is_ignored_and_replaced(user_api, sessions, monkeypatch):
    client, _ = user_api
    register(client)
    calls = mock_chat(monkeypatch)
    assert client.post("/recommendations/explain", json={}).status_code == 200
    with sessions.begin() as session:
        cache = session.scalar(select(LlmCache))
        cache.payload = [{"item_id": 999999, "explanation": UKRAINIAN}] * 10
    assert all(row["explanation"] is None for row in client.get("/recommendations").json())
    result = client.post("/recommendations/explain", json={}).json()
    assert len(result) == 10 and all(row["explanation"] == UKRAINIAN for row in result)
    assert len(calls) == 2


def test_overall_deadline_returns_hybrid(user_api, sessions, monkeypatch):
    client, _ = user_api
    register(client)
    monkeypatch.setattr("app.api.recommendations.EXPLANATION_TIMEOUT_SECONDS", 0.1)

    async def slow(self, messages, schema, model):
        await asyncio.sleep(1)
        return valid_payload()

    monkeypatch.setattr(OllamaClient, "chat_json", slow)
    result = client.post("/recommendations/explain", json={})
    assert result.status_code == 200 and len(result.json()) == 10
    assert all(row["explanation"] is None for row in result.json())
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(LlmCache)) == 0


def test_explain_authentication_and_domain_validation(user_api, monkeypatch):
    client, _ = user_api
    calls = mock_chat(monkeypatch)
    assert client.post("/recommendations/explain", json={}).status_code == 401
    register(client)
    assert client.post("/recommendations/explain", json={"domain": "invalid"}).status_code == 422
    assert not calls


def test_prompts_are_bounded_numbered_and_do_not_mutate_input():
    profile = {"high_rated": [{"title": "x" * 120, "genres": ["genre" * 8] * 4}] * 15,
               "low_rated": [], "recent_views": [], "top_genres": ["Drama"]}
    candidates = [{"n": n, "title": "x" * 120, "genres": ["genre" * 8] * 4,
                   "description": "a" * 200} for n in range(1, 31)]
    messages = build_messages(profile, candidates)
    assert len(messages[1]["content"]) <= 14000
    data = json.loads(messages[1]["content"])
    assert [row["n"] for row in data["candidates"]] == list(range(1, 31))
    assert all("id" not in row for row in data["candidates"])
    assert candidates[0]["description"] == "a" * 200
    assert response_schema(30)["properties"]["recommendations"]["maxItems"] == 10
    assert validate_choices({"recommendations": []}, 30) == []


def test_evidence_uses_only_shared_metadata_and_correct_genre_labels():
    liked = Item(id=1, domain="movie", title="Liked film", genres=["Thriller"], creators=[])
    candidate = Item(id=2, domain="movie", title="Candidate", genres=["Thriller"], creators=[])
    rating = Rating(value=9, implicit=False)
    evidence = candidate_evidence(candidate, [(rating, liked)])
    assert "Liked film" in evidence and "9/10" in evidence and "трилер" in evidence
    assert "трейлер" not in evidence
    liked_book = Item(id=3, domain="book", title="Liked book", genres=[], creators=["Author"])
    book = Item(id=4, domain="book", title="Another book", genres=[], creators=["Author"])
    assert "Author" in candidate_evidence(book, [(rating, liked_book)])
    unknown = Item(id=5, domain="book", title="Unknown", genres=[], creators=[], rating_count=10)
    fallback = candidate_evidence(unknown, [(rating, liked_book)])
    assert "популярністю" in fallback and "жанр" not in fallback


def test_chat_client_sends_schema_disables_thinking_and_parses_json():
    async def run():
        requests = []

        def request(req):
            requests.append(json.loads(req.content))
            return httpx.Response(200, json={"message": {"content":
                '<think>ignored</think>' + json.dumps(valid_payload())}})

        client = OllamaClient("http://ollama")
        await client.aclose()
        client._http = httpx.AsyncClient(base_url="http://ollama",
                                         transport=httpx.MockTransport(request))
        try:
            schema = response_schema(30)
            result = await client.chat_json(
                [{"role": "user", "content": "input"}], schema, "qwen3:8b",
            )
            assert len(result["recommendations"]) == 10
            assert requests[0]["think"] is False and requests[0]["stream"] is False
            assert requests[0]["format"] == schema
            assert requests[0]["options"]["num_ctx"] == 8192
        finally:
            await client.aclose()
    asyncio.run(run())
