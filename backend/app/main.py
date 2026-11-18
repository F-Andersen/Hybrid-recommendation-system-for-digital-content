from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from weakref import WeakValueDictionary

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool

from app.api import (
    admin,
    auth,
    evaluation,
    health,
    items,
    me,
    onboarding,
    ratings,
    recommendations,
)
from app.core.config import get_settings
from app.llm.client import OllamaClient
from app.recsys.als import load_available_models


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.ollama = OllamaClient(settings.ollama_base_url)
    app.state.als_models = await run_in_threadpool(load_available_models, settings.artifacts_dir)
    app.state.llm_locks = WeakValueDictionary()
    yield
    await app.state.ollama.aclose()


app = FastAPI(title="Hybrid Recommender API", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(items.router)
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(ratings.router)
app.include_router(me.router)
app.include_router(onboarding.router)
app.include_router(recommendations.router)
app.include_router(evaluation.router)
