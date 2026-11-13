from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import engine
from app.llm.client import OllamaClient, normalize_model_name

router = APIRouter(tags=["health"])


class DbStatus(BaseModel):
    ok: bool
    pgvector: bool = False
    error: str | None = None


class OllamaStatus(BaseModel):
    ok: bool
    models_required: list[str]
    models_missing: list[str]
    error: str | None = None


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded"
    db: DbStatus
    ollama: OllamaStatus
    als_loaded: dict[str, bool]


def check_db() -> DbStatus:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            has_vector = conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
            ).scalar_one()
        return DbStatus(ok=True, pgvector=bool(has_vector))
    except Exception as exc:  # health must report, not raise
        return DbStatus(ok=False, error=f"{type(exc).__name__}: {exc}")


async def check_ollama(client: OllamaClient, required: list[str]) -> OllamaStatus:
    try:
        available = {normalize_model_name(m) for m in await client.list_models()}
    except Exception as exc:
        return OllamaStatus(
            ok=False,
            models_required=required,
            models_missing=required,
            error=f"{type(exc).__name__}: {exc}",
        )
    missing = [m for m in required if normalize_model_name(m) not in available]
    return OllamaStatus(ok=True, models_required=required, models_missing=missing)


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    settings = get_settings()
    db = await run_in_threadpool(check_db)
    ollama = await check_ollama(
        request.app.state.ollama, [settings.llm_model, settings.embed_model]
    )
    als_loaded = {d: d in request.app.state.als_models for d in ("movie", "book")}
    healthy = db.ok and db.pgvector and ollama.ok and not ollama.models_missing
    return HealthResponse(
        status="ok" if healthy else "degraded", db=db, ollama=ollama, als_loaded=als_loaded
    )
