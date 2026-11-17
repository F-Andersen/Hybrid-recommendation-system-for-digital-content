import httpx

from app.recsys.vectors import normalize_vectors


def normalize_model_name(name: str) -> str:
    """Ollama reports untagged models as '<name>:latest'."""
    return name if ":" in name else f"{name}:latest"


class OllamaClient:
    """Thin async wrapper over the Ollama HTTP API.

    Embeddings are validated and L2-normalized; JSON chat is added in stage 5.
    """

    def __init__(self, base_url: str, timeout: float = 120.0) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url, timeout=httpx.Timeout(timeout, connect=5.0)
        )

    async def list_models(self) -> list[str]:
        response = await self._http.get("/api/tags")
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", [])]

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        if not texts:
            return []
        response = await self._http.post("/api/embed", json={
            "model": model, "input": texts, "truncate": False, "keep_alive": "30m",
        })
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or "embeddings" not in payload:
            raise ValueError("Ollama не повернув ембединги")
        return normalize_vectors(payload["embeddings"], len(texts)).tolist()

    async def aclose(self) -> None:
        await self._http.aclose()
