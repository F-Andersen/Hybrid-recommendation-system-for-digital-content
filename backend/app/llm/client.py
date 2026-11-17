import json
import re
from typing import Any

import httpx

from app.recsys.vectors import normalize_vectors


def normalize_model_name(name: str) -> str:
    """Ollama reports untagged models as '<name>:latest'."""
    return name if ":" in name else f"{name}:latest"


class OllamaClient:
    """Thin async wrapper over the Ollama HTTP API.

    Embeddings are normalized; chat uses a JSON schema and disables thinking.
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

    async def chat_json(
        self, messages: list[dict[str, str]], schema: dict[str, Any], model: str,
    ) -> dict[str, Any]:
        response = await self._http.post("/api/chat", json={
            "model": model, "messages": messages, "format": schema,
            "stream": False, "think": False, "keep_alive": "30m",
            "options": {"temperature": 0.3, "num_ctx": 8192, "num_predict": 2048, "seed": 42},
        })
        response.raise_for_status()
        envelope = response.json()
        message = envelope.get("message") if isinstance(envelope, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ValueError("Ollama не повернув текст JSON")
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        payload = json.loads(content)
        if not isinstance(payload, dict):
            raise ValueError("Відповідь Ollama має бути JSON-об'єктом")
        return payload
