import httpx
import pytest

from app.core.config import Settings
from app.integrations.tmdb import TmdbClient, TmdbError


def settings(key="test-key", token="test-token"):
    return Settings(_env_file=None, tmdb_api_key=key, tmdb_access_token=token)


@pytest.mark.parametrize(("mode", "expected"), [
    ("auto", "token"), ("token", "token"), ("key", "key"),
])
def test_authentication_modes(mode, expected):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"images": {"secure_base_url": "https://image.tmdb.org/"}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        client = TmdbClient(http, settings(), auth=mode)
        assert client.configuration()["images"]
        assert client.auth == expected
    request, = requests
    assert request.url.host == "api.themoviedb.org"
    if expected == "token":
        assert request.headers["Authorization"] == "Bearer test-token"
        assert "api_key" not in request.url.params
    else:
        assert request.url.params["api_key"] == "test-key"
        assert "Authorization" not in request.headers


def test_auto_uses_key_when_token_is_empty():
    with httpx.Client() as http:
        assert TmdbClient(http, settings(token="")).auth == "key"
        assert TmdbClient(http, settings(token="Bearer test-token")).auth == "token"


@pytest.mark.parametrize(("mode", "variable"), [
    ("auto", "TMDB_API_KEY"), ("key", "TMDB_API_KEY"), ("token", "TMDB_ACCESS_TOKEN"),
])
def test_missing_credentials(mode, variable):
    with httpx.Client() as http, pytest.raises(TmdbError, match=variable):
        TmdbClient(http, settings(key="", token=""), auth=mode)


def test_authentication_failure_does_not_fallback_or_reveal_secrets():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(401, json={"status_message": "test-key test-token"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        for mode in ("auto", "key"):
            with pytest.raises(TmdbError, match="HTTP 401") as error:
                TmdbClient(http, settings(), auth=mode).configuration()
            assert "test-key" not in str(error.value)
            assert "test-token" not in str(error.value)
    assert len(calls) == 2
    assert "test-key" not in repr(settings())
    assert "test-token" not in repr(settings())


def test_rate_limit_retry(monkeypatch):
    pauses = []
    calls = []
    monkeypatch.setattr("app.integrations.tmdb.time.sleep", pauses.append)

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"id": 603})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        assert TmdbClient(http, settings()).movie(603) == {"id": 603}
    assert len(calls) == 2
    assert pauses == [2]


def test_transport_error_is_redacted_and_retried(monkeypatch):
    monkeypatch.setattr("app.integrations.tmdb.time.sleep", lambda _: None)
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ConnectError("test-key test-token", request=request)

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as http,
        pytest.raises(TmdbError) as error,
    ):
        TmdbClient(http, settings()).configuration()
    assert len(calls) == 4
    assert "test-key" not in str(error.value)
    assert "test-token" not in str(error.value)


@pytest.mark.parametrize("payload", [[], "invalid"])
def test_unexpected_response_shape(payload):
    with httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=payload),
    )) as http, pytest.raises(TmdbError, match="структуру"):
        TmdbClient(http, settings()).configuration()


def test_invalid_json():
    with httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, text="not json"),
    )) as http, pytest.raises(TmdbError, match="JSON"):
        TmdbClient(http, settings()).configuration()


@pytest.mark.parametrize("tmdb_id", [True, "603", 0, -1])
def test_invalid_movie_id(tmdb_id):
    with httpx.Client() as http, pytest.raises(ValueError, match="ID"):
        TmdbClient(http, settings()).movie(tmdb_id)
