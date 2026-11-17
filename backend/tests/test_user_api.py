from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.core.security import create_session_token, verify_password
from app.db.models import Item, LlmCache, Rating, User
from app.db.session import get_db
from app.main import app
from app.recsys.als import AlsParameters, train_als
from app.recsys.types import HistoryRating

PASSWORD = "correct horse battery staple"


@pytest.fixture
def user_api(sessions, catalog, tmp_path, monkeypatch):
    settings = Settings(_env_file=None, jwt_secret="test-session-key-" * 4,
                        artifacts_dir=tmp_path, session_cookie_secure=False)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.main.load_available_models", lambda _: {})

    def database():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            yield client, settings
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_settings, None)


def register(client, email="reader@example.com", password=PASSWORD):
    response = client.post("/auth/register", json={
        "email": email, "password": password, "display_name": "Читач",
    })
    assert response.status_code == 201, response.text
    return response.json(), client.cookies.get("session")


def use_session(client, token):
    client.cookies.clear()
    client.cookies.set("session", token)


@pytest.fixture
def recommendation_model(user_api, sessions):
    with sessions.begin() as session:
        item_ids = list(session.scalars(select(Item.id).where(
            Item.domain == "movie",
        ).order_by(Item.id)))
        users = [User(source="movielens", external_id=str(index), display_name=f"Dataset {index}")
                 for index in range(12)]
        session.add_all(users)
        session.flush()
        user_ids = [user.id for user in users]
        interactions = []
        for index, user_id in enumerate(user_ids):
            for offset in range(5):
                item_id = item_ids[(index * 2 + offset) % 30]
                session.add(Rating(user_id=user_id, item_id=item_id, value=9, implicit=False))
                interactions.append((user_id, HistoryRating(item_id, 9)))
    model = train_als(user_ids, item_ids, interactions,
                      AlsParameters(factors=8, iterations=5, num_threads=1))
    app.state.als_models = {"movie": model}
    return model


def test_registration_login_logout_cookie_and_password_hash(user_api, sessions):
    client, _ = user_api
    password = "  пароль із пробілами  "
    profile, _ = register(client, " Reader@Example.COM ", password)
    assert profile["email"] == "reader@example.com"
    assert profile["rating_counts"] == {"movie": 0, "book": 0}
    assert "password_hash" not in profile and "token" not in profile
    with sessions() as session:
        stored = session.get(User, profile["id"])
        assert stored.password_hash.startswith("$argon2id$")
        assert verify_password(stored.password_hash, password)
        assert not verify_password(stored.password_hash, password.strip())
    duplicate = client.post("/auth/register", json={
        "email": "READER@example.com", "password": PASSWORD, "display_name": "Other",
    })
    assert duplicate.status_code == 409
    assert client.get("/auth/me").json()["id"] == profile["id"]
    logout = client.post("/auth/logout")
    assert logout.status_code == 204
    assert "max-age=0" in logout.headers["set-cookie"].lower()
    assert client.get("/auth/me").status_code == 401
    login = client.post("/auth/login", json={"email": "READER@EXAMPLE.COM", "password": password})
    assert login.status_code == 200
    cookie = login.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "max-age=604800" in cookie
    assert "path=/" in cookie
    assert client.get("/auth/me").json()["id"] == profile["id"]
    for email in ("reader@example.com", "absent@example.com"):
        assert client.post("/auth/login", json={
            "email": email, "password": "wrong",
        }).status_code == 401


@pytest.mark.parametrize(("method", "path"), [
    ("get", "/auth/me"), ("get", "/me/ratings"), ("get", "/me/history"),
    ("get", "/recommendations"), ("get", "/onboarding/items"),
    ("put", "/ratings/1"), ("delete", "/ratings/1"),
])
def test_protected_endpoints_require_cookie(user_api, method, path):
    client, _ = user_api
    kwargs = {"json": {"value": 9}} if method == "put" else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401


@pytest.mark.parametrize("kind", ["tampered", "expired", "missing_exp", "unknown", "oversized_sub"])
def test_invalid_tokens_are_401(user_api, kind):
    client, settings = user_api
    profile, token = register(client)
    if kind == "tampered":
        token = create_session_token(profile["id"], "a-different-key-" * 4)
    else:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], audience="web")
        if kind == "expired":
            payload["exp"] = int((datetime.now(UTC) - timedelta(seconds=5)).timestamp())
        elif kind == "missing_exp":
            payload.pop("exp")
        elif kind == "unknown":
            payload["sub"] = "99999999"
        elif kind == "oversized_sub":
            payload["sub"] = str(2 ** 70)
        token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    use_session(client, token)
    assert client.get("/auth/me").status_code == 401
    assert client.put("/ratings/1", json={"value": 9}).status_code == 401


def test_dataset_identity_cannot_be_used_as_web_session(user_api, sessions):
    client, settings = user_api
    with sessions.begin() as session:
        user = User(source="movielens", external_id="1", display_name="Dataset")
        session.add(user)
        session.flush()
        user_id = user.id
    use_session(client, create_session_token(user_id, settings.jwt_secret))
    assert client.get("/auth/me").status_code == 401


def test_weak_secret_is_rejected_before_creating_user(user_api, sessions):
    client, settings = user_api
    settings.jwt_secret = "change-me"
    assert client.post("/auth/register", json={
        "email": "reader@example.com", "password": PASSWORD, "display_name": "Reader",
    }).status_code == 503
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0


def test_secure_cookie_flag_can_be_enabled(user_api):
    client, settings = user_api
    settings.session_cookie_secure = True
    response = client.post("/auth/register", json={
        "email": "reader@example.com", "password": PASSWORD, "display_name": "Reader",
    })
    assert response.status_code == 201
    assert "; secure" in response.headers["set-cookie"].lower()


@pytest.mark.parametrize("change", [
    {"email": "bad-address"}, {"email": "a..b@example.com"}, {"email": "a@-example.com"},
    {"password": "short"}, {"password": "        "}, {"display_name": "  "},
])
def test_invalid_registration_data(user_api, change):
    client, _ = user_api
    payload = {"email": "reader@example.com", "password": PASSWORD, "display_name": "Reader"}
    payload.update(change)
    assert client.post("/auth/register", json=payload).status_code == 422


def test_rating_upsert_delete_aggregates_and_user_isolation(user_api, sessions):
    client, _ = user_api
    first, first_token = register(client)
    for value in (9, 3, 3):
        assert client.put("/ratings/1", json={"value": value}).status_code == 200
    with sessions() as session:
        item = session.get(Item, 1)
        assert (item.rating_count, item.rating_avg) == (1, 3)
        assert item.embedding is not None
        assert session.scalar(select(func.count()).select_from(Rating)) == 1
    second, second_token = register(client, "second@example.com")
    assert client.get("/me/ratings").json()["total"] == 0
    assert client.put("/ratings/1", json={"value": 9}).status_code == 200
    with sessions() as session:
        item = session.get(Item, 1)
        assert (item.rating_count, item.rating_avg) == (2, 6)
    use_session(client, first_token)
    assert client.delete("/ratings/1").status_code == 204
    assert client.delete("/ratings/1").status_code == 204
    with sessions() as session:
        item = session.get(Item, 1)
        assert (item.rating_count, item.rating_avg) == (1, 9)
        assert session.get(Rating, (first["id"], 1)) is None
        assert session.get(Rating, (second["id"], 1)).value == 9
    use_session(client, second_token)
    assert client.get("/items/1").json()["my_rating"] == 9
    assert client.delete("/ratings/1").status_code == 204
    with sessions() as session:
        item = session.get(Item, 1)
        assert (item.rating_count, item.rating_avg) == (0, 0)


def test_profile_history_filters_and_cache_invalidation(user_api, sessions):
    client, _ = user_api
    profile, _ = register(client)
    with sessions.begin() as session:
        session.add(LlmCache(user_id=profile["id"], domain="movie", profile_hash="old", payload=[]))
        session.add(LlmCache(user_id=profile["id"], domain="book", profile_hash="book", payload=[]))
    assert client.put("/ratings/1", json={"value": 8}).status_code == 200
    with sessions() as session:
        assert session.scalars(select(LlmCache.domain)).all() == ["book"]
    assert client.put("/ratings/2", json={"value": 9}).status_code == 200
    assert client.put("/ratings/41", json={"value": 10}).status_code == 200
    assert client.get("/auth/me").json()["rating_counts"] == {"movie": 2, "book": 1}
    rated = client.get("/me/ratings?domain=movie&page_size=1").json()
    assert rated["total"] == 2 and len(rated["items"]) == 1
    second_page = client.get("/me/ratings?domain=movie&page_size=1&page=2").json()
    assert rated["items"][0]["item"]["id"] != second_page["items"][0]["item"]["id"]
    for item_id in (1, 1, 41):
        assert client.get(f"/items/{item_id}").status_code == 200
    history = client.get("/me/history?page_size=2").json()
    assert history["total"] == 3 and len(history["items"]) == 2
    assert history["items"][0]["item"]["domain"] == "book"
    assert client.get("/me/history?domain=movie").json()["total"] == 2
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(LlmCache)) == 0
    register(client, "another@example.com")
    assert client.get(f"/me/history?user_id={profile['id']}").json()["total"] == 0
    assert client.get("/me/ratings").json()["total"] == 0


@pytest.mark.parametrize("value", [0, 11, 8.5, True, "9"])
def test_ratings_require_integer_scale_1_to_10(user_api, value):
    client, _ = user_api
    register(client)
    assert client.put("/ratings/1", json={"value": value}).status_code == 422


def test_missing_rating_target_and_pagination_validation(user_api):
    client, _ = user_api
    register(client)
    assert client.put("/ratings/999999", json={"value": 8}).status_code == 404
    assert client.delete("/ratings/999999").status_code == 404
    assert client.get("/me/ratings?page=0").status_code == 422
    assert client.get("/me/history?page_size=101").status_code == 422


def test_registration_five_ratings_recommendation_models(user_api, recommendation_model):
    client, _ = user_api
    register(client)
    onboarding = client.get("/onboarding/items?k=5").json()
    assert len(onboarding) == 5
    assert {genre for item in onboarding for genre in item["genres"]} == {"Action", "Drama"}
    rated_ids = {item["id"] for item in onboarding}
    for item_id in rated_ids:
        assert client.put(f"/ratings/{item_id}", json={"value": 9}).status_code == 200
    viewed_id = next(item for item in recommendation_model.item_ids if item not in rated_ids)
    assert client.get(f"/items/{viewed_id}").status_code == 200
    for model in ("hybrid", "als", "content", "popular"):
        response = client.get(f"/recommendations?domain=movie&model={model}")
        assert response.status_code == 200
        result = response.json()
        assert len(result) == 10
        assert not (rated_ids | {viewed_id}) & {row["item"]["id"] for row in result}
        assert all(row["explanation"] is None and 0 <= row["score"] <= 1 for row in result)
        assert all(sum(row["sources"].values()) == pytest.approx(row["score"]) for row in result)
    assert client.get("/auth/me").json()["rating_counts"] == {"movie": 5, "book": 0}
    assert not rated_ids & {item["id"] for item in client.get("/onboarding/items").json()}
    books = client.get("/recommendations?domain=book").json()
    assert len(books) == 1 and books[0]["item"]["domain"] == "book"


def test_cold_negative_and_missing_als_fallbacks(user_api):
    client, _ = user_api
    register(client)
    cold = client.get("/recommendations").json()
    assert len(cold) == 10 and all(row["sources"]["popular"] > 0 for row in cold)
    assert client.get("/recommendations?model=content").json() == []
    assert client.get("/recommendations?model=als").status_code == 503
    for item_id in range(1, 6):
        client.put(f"/ratings/{item_id}", json={"value": 1})
    negative = client.get("/recommendations").json()
    assert len(negative) == 10
    assert not set(range(1, 6)) & {row["item"]["id"] for row in negative}
    for item_id in range(1, 6):
        client.put(f"/ratings/{item_id}", json={"value": 9})
    content = client.get("/recommendations").json()
    assert len(content) == 10 and content[0]["sources"]["content"] > 0


@pytest.mark.parametrize("query", ["k=0", "k=51", "domain=invalid", "model=unknown"])
def test_invalid_recommendation_queries(user_api, query):
    client, _ = user_api
    register(client)
    assert client.get("/recommendations?" + query).status_code == 422
