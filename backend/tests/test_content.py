import asyncio
import json

import httpx
import numpy as np
import pytest
from sqlalchemy import func, select

from app.db.models import Item
from app.llm.client import OllamaClient
from app.recsys.content import (
    NumpyContentRecommender,
    SqlContentRecommender,
    build_item_text,
    build_user_profile,
)
from app.recsys.types import HistoryRating, UserHistory
from scripts.build_embeddings import build_embeddings


def test_item_text_handles_metadata_and_description_limit():
    book = Item(domain="book", title="Book", year=2000, creators=["Author"], genres=["History"],
                meta={"publisher": "Publisher"}, description="a" * 2000)
    value = build_item_text(book)
    assert value == ("Type: book\nTitle: Book\nYear: 2000\nAuthors: Author\n"
                     "Publisher: Publisher\nGenres/subjects: History\nDescription: " + "a" * 1500)
    assert build_item_text(Item(domain="movie", title="Film")) == "Type: movie\nTitle: Film"


def test_profiles_use_negative_ratings_and_deduplicate_views():
    vectors = {1: np.eye(1, 1024, 0, dtype=np.float32)[0],
               2: np.eye(1, 1024, 1, dtype=np.float32)[0]}
    history = UserHistory([HistoryRating(1, 10), HistoryRating(2, 1)], [1, 1, 2])
    result = build_user_profile(history, vectors)
    assert result[:2] == pytest.approx([1 / np.sqrt(2), -1 / np.sqrt(2)])
    assert build_user_profile(UserHistory([HistoryRating(2, 1)], [2]), vectors) is None
    assert build_user_profile(UserHistory([HistoryRating(999, 10)]), vectors) is None
    assert build_user_profile(UserHistory(views=[1, 1]), vectors) == pytest.approx(vectors[1])
    assert build_user_profile(UserHistory([HistoryRating(1, None, True)]), vectors) is not None


def test_sql_and_numpy_top10_agree(sessions, catalog):
    with sessions() as session:
        rows = session.execute(select(Item.id, Item.embedding).where(
            Item.domain == "movie",
        ).order_by(Item.id)).all()
        history = UserHistory([HistoryRating(rows[0][0], 10), HistoryRating(rows[1][0], 2)])
        excluded = {rows[2][0]}
        sql = SqlContentRecommender(session, "movie", exact=True).recommend(history, 10, excluded)
        offline = NumpyContentRecommender([row[0] for row in rows], [row[1] for row in rows])
        numpy = offline.recommend(history, 10, excluded)
        assert [key for key, _ in sql] == [key for key, _ in numpy]
        assert [score for _, score in sql] == pytest.approx([score for _, score in numpy], abs=1e-6)
        assert not {rows[i][0] for i in range(3)} & {key for key, _ in sql}
        assert len(sql) == 10
        assert SqlContentRecommender(session, "movie").recommend(UserHistory(), 10, set()) == []


def test_empty_catalog_and_zero_profile_return_empty():
    model = NumpyContentRecommender([], [])
    assert model.recommend(UserHistory(), 10, set()) == []
    assert model.rank_vector(np.ones(1024), 10, set()) == []


def test_changed_content_invalidates_embedding_but_stats_do_not(sessions, catalog):
    with sessions.begin() as session:
        item = session.scalar(select(Item).order_by(Item.id))
        item_id = item.id
        item.rating_count += 1
        item.cover_url = "https://example.org/cover.jpg"
        session.flush()
        session.refresh(item)
        assert item.embedding is not None
        item.meta = {"publisher": "New publisher"}
        session.flush()
        session.refresh(item)
        assert item.embedding is None
        item.embedding = catalog[0]
    with sessions.begin() as session:
        item = session.get(Item, item_id)
        item.title = "Changed title"
        session.flush()
        session.refresh(item)
        assert item.embedding is None


def test_builder_resumes_and_never_saves_stale_text(sessions):
    with sessions.begin() as session:
        index = next(index for index in Item.__table__.indexes
                     if index.name == "ix_items_embedding_hnsw")
        index.drop(session.connection())
        for index in range(2):
            session.add(Item(domain="movie", source="movielens", external_id=str(index),
                             title="Original", creators=[], genres=[]))
    calls = []

    async def embed(texts):
        calls.append(texts)
        if len(calls) == 1:
            with sessions.begin() as session:
                item = session.scalar(select(Item).order_by(Item.id))
                item.title = "Changed"
        return np.ones((len(texts), 1024)).tolist()

    result = asyncio.run(build_embeddings(sessions, embed))
    assert (result["written"], result["stale"], result["remaining"]) == (2, 1, 0)
    assert len(calls) == 2
    assert "Changed" in calls[1][0]
    assert asyncio.run(build_embeddings(sessions, embed))["written"] == 0
    assert len(calls) == 2
    with sessions() as session:
        for vector in session.scalars(select(Item.embedding)):
            assert np.linalg.norm(vector) == pytest.approx(1, abs=1e-6)


def test_invalid_embeddings_roll_back_current_batch(sessions):
    with sessions.begin() as session:
        session.add(Item(domain="book", source="bookcrossing", external_id="1", title="Book"))

    async def broken(texts):
        return [[0.0] * 1024]

    with pytest.raises(ValueError, match="нульовий"):
        asyncio.run(build_embeddings(sessions, broken))
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Item).where(
            Item.embedding.is_(None),
        )) == 1


@pytest.mark.parametrize("payload", [
    {}, {"embeddings": [[1.0] * 1023]}, {"embeddings": [[0.0] * 1024]},
    {"embeddings": [[float("nan")] * 1024]}, {"embeddings": []},
])
def test_ollama_rejects_invalid_embedding_response(payload):
    async def run():
        client = OllamaClient("http://ollama")
        await client.aclose()
        client._http = httpx.AsyncClient(
            base_url="http://ollama", transport=httpx.MockTransport(
                lambda _: httpx.Response(200, content=json.dumps(payload)),
            ),
        )
        try:
            with pytest.raises(ValueError):
                await client.embed(["Text"], "bge-m3")
        finally:
            await client.aclose()
    asyncio.run(run())


def test_ollama_sends_batch_and_normalizes_vectors():
    async def run():
        client = OllamaClient("http://ollama")
        await client.aclose()
        requests = []

        def request(req):
            requests.append(req)
            return httpx.Response(200, json={"embeddings": [[2.0] * 1024, [3.0] * 1024]})

        client._http = httpx.AsyncClient(
            base_url="http://ollama", transport=httpx.MockTransport(request),
        )
        try:
            vectors = await client.embed(["First", "Second"], "bge-m3")
            assert np.linalg.norm(vectors, axis=1) == pytest.approx([1, 1])
            assert requests[0].url.path == "/api/embed"
            assert await client.embed([], "bge-m3") == []
            assert len(requests) == 1
        finally:
            await client.aclose()
    asyncio.run(run())
