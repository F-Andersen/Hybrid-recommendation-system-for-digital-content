from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool

from app.api import admin, health, items
from app.core.config import get_settings
from app.llm.client import OllamaClient
from app.recsys.als import load_available_models


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.ollama = OllamaClient(settings.ollama_base_url)
    app.state.als_models = await run_in_threadpool(load_available_models, settings.artifacts_dir)
    yield
    await app.state.ollama.aclose()


app = FastAPI(title="Hybrid Recommender API", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(items.router)
app.include_router(admin.router)
