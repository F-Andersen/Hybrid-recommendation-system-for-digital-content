import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import Interaction, Item
from app.db.session import get_db
from app.main import app


@pytest.fixture
def catalog_client(sessions, catalog, monkeypatch):
    monkeypatch.setattr("app.main.load_available_models", lambda _: {})
    def database():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = database
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_catalog_filters_and_pagination(catalog_client):
    result = catalog_client.get("/items", params={
        "domain": "movie", "q": "Movie 3", "genre": "Action", "page_size": 2,
    }).json()
    assert result["total"] == 5
    assert result["page"] == 1
    assert len(result["items"]) == 2
    assert all("Action" in item["genres"] for item in result["items"])
    second = catalog_client.get("/items", params={
        "q": "Movie 3", "genre": "Action", "page_size": 2, "page": 2,
    }).json()
    assert not {item["id"] for item in result["items"]} & {
        item["id"] for item in second["items"]
    }
    assert catalog_client.get("/items", params={"q": "%_"}).json()["total"] == 1
    assert catalog_client.get("/items", params={"page": 999}).json()["items"] == []
    assert catalog_client.get("/items", params={"domain": "book"}).json()["total"] == 1


def test_catalog_sort_and_genre_counts(catalog_client):
    for sort in ("popular", "year"):
        result = catalog_client.get("/items", params={"sort": sort}).json()
        assert result["items"][0]["title"] == "Movie 39"
    assert catalog_client.get("/items/genres").json() == [
        {"genre": "Action", "count": 20}, {"genre": "Drama", "count": 20},
    ]
    assert catalog_client.get("/items/genres?domain=book").json() == [
        {"genre": "Fiction", "count": 1},
    ]


def test_detail_and_similarity_are_public_and_never_return_vectors(catalog_client, sessions):
    item = catalog_client.get("/items").json()["items"][0]
    response = catalog_client.get(f"/items/{item['id']}")
    assert response.status_code == 200
    assert response.json()["my_rating"] is None
    assert "embedding" not in response.json()
    similar = catalog_client.get(f"/items/{item['id']}/similar").json()
    assert len(similar) == 12
    assert item["id"] not in {row["item"]["id"] for row in similar}
    assert all(row["item"]["domain"] == "movie" for row in similar)
    assert [row["score"] for row in similar] == sorted(
        [row["score"] for row in similar], reverse=True,
    )
    assert all(-1 <= row["score"] <= 1 for row in similar)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Interaction)) == 0


@pytest.mark.parametrize("path", ["/items/999999", "/items/999999/similar"])
def test_missing_items_are_404(catalog_client, path):
    assert catalog_client.get(path).status_code == 404


def test_item_without_embedding_has_no_similar_results(catalog_client, sessions):
    with sessions.begin() as session:
        item = session.scalar(select(Item).order_by(Item.id))
        item_id = item.id
        item.embedding = None
    assert catalog_client.get(f"/items/{item_id}/similar").json() == []


@pytest.mark.parametrize("query", [
    "domain=invalid", "page=0", "page_size=101", "sort=unknown", "page_size=-1",
])
def test_invalid_catalog_queries_are_422(catalog_client, query):
    assert catalog_client.get("/items?" + query).status_code == 422
