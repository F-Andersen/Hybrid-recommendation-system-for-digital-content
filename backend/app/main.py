from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health, items
from app.core.config import get_settings
from app.llm.client import OllamaClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.ollama = OllamaClient(settings.ollama_base_url)
    # filled with trained ALS artifacts in stage 3: {"movie": ..., "book": ...}
    app.state.als_models = {}
    yield
    await app.state.ollama.aclose()


app = FastAPI(title="Hybrid Recommender API", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(items.router)
