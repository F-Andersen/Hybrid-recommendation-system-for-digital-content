"""TMDB application authentication with errors that never expose credentials."""

import time
from typing import Any, Literal

import httpx

from app.core.config import Settings

AuthMode = Literal["auto", "key", "token"]
API_BASE = "https://api.themoviedb.org/3"


class TmdbError(RuntimeError):
    """A safe, user-facing TMDB error without request URLs or headers."""


class TmdbClient:
    def __init__(
        self, http: httpx.Client, settings: Settings, auth: AuthMode = "auto",
    ) -> None:
        key = settings.tmdb_api_key.get_secret_value().strip()
        token = settings.tmdb_access_token.get_secret_value().strip()
        token = token.removeprefix("Bearer ").strip()
        if auth not in {"auto", "key", "token"}:
            raise ValueError("Невідомий спосіб авторизації TMDB")
        self.auth: Literal["key", "token"] = (
            "token" if token else "key"
        ) if auth == "auto" else auth
        credential = token if self.auth == "token" else key
        if not credential:
            variable = "TMDB_ACCESS_TOKEN" if self.auth == "token" else "TMDB_API_KEY"
            raise TmdbError(f"Заповніть {variable} у локальному .env")
        if any(character.isspace() for character in credential):
            raise TmdbError("Ключ TMDB містить зайві пробіли або переноси рядків")
        self.http = http
        self._headers = {"Authorization": f"Bearer {token}"} if self.auth == "token" else {}
        self._params = {"api_key": key} if self.auth == "key" else {}

    def configuration(self) -> dict[str, Any]:
        return self._get("configuration")

    def movie(self, tmdb_id: int) -> dict[str, Any]:
        if isinstance(tmdb_id, bool) or not isinstance(tmdb_id, int) or tmdb_id < 1:
            raise ValueError("ID фільму TMDB має бути додатним цілим числом")
        return self._get(f"movie/{tmdb_id}")

    def _get(self, endpoint: str) -> dict[str, Any]:
        for attempt in range(4):
            try:
                response = self.http.get(
                    f"{API_BASE}/{endpoint}", params=self._params, headers=self._headers,
                    follow_redirects=False,
                )
            except httpx.TransportError:
                if attempt == 3:
                    raise TmdbError("Не вдалося з'єднатися з TMDB") from None
                time.sleep(2 ** attempt)
                continue
            if (response.status_code == 429 or response.status_code >= 500) and attempt < 3:
                try:
                    delay = float(response.headers.get("Retry-After", ""))
                except ValueError:
                    delay = 2 ** attempt
                time.sleep(min(60.0, max(1.0, delay)))
                continue
            if not response.is_success:
                # HTTPStatusError includes the URL, which can contain an API key.
                raise TmdbError(f"TMDB повернув HTTP {response.status_code}")
            try:
                payload = response.json()
            except ValueError:
                raise TmdbError("TMDB повернув некоректний JSON") from None
            if not isinstance(payload, dict):
                raise TmdbError("TMDB повернув неочікувану структуру даних")
            return payload
        raise TmdbError("TMDB тимчасово недоступний")
