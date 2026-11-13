import httpx


def normalize_model_name(name: str) -> str:
    """Ollama reports untagged models as '<name>:latest'."""
    return name if ":" in name else f"{name}:latest"


class OllamaClient:
    """Thin async wrapper over the Ollama HTTP API.

    Stage 0 only needs model listing; embed() and chat_json() are added in stages 2 and 5.
    """

    def __init__(self, base_url: str, timeout: float = 120.0) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url, timeout=httpx.Timeout(timeout, connect=5.0)
        )

    async def list_models(self) -> list[str]:
        response = await self._http.get("/api/tags")
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", [])]

    async def aclose(self) -> None:
        await self._http.aclose()
