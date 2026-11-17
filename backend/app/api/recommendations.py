import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import defer

from app.api.deps import CurrentUser, Db, SettingsDep
from app.core.config import Settings
from app.db.models import Item
from app.llm.rerank import rerank
from app.recsys.types import Domain
from app.schemas.items import ItemSummary
from app.schemas.recommendations import ExplainRequest, RecommendationItem, RecommendationSources
from app.services.explanations import (
    ExplanationSnapshot,
    cached_result,
    merge_choices,
    prepare_explanation,
    save_explanations,
)
from app.services.recommendations import ModelName, load_history, recommend

router = APIRouter(prefix="/recommendations", tags=["recommendations"])
logger = logging.getLogger(__name__)
EXPLANATION_TIMEOUT_SECONDS = 120


@router.get("", response_model=list[RecommendationItem])
def recommendations(
    request: Request, db: Db, user: CurrentUser, settings: SettingsDep, domain: Domain = "movie",
    model: ModelName = "hybrid", k: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[RecommendationItem]:
    als = request.app.state.als_models.get(domain)
    if model == "hybrid":
        snapshot = prepare_explanation(db, user.id, domain, als, settings.llm_model, k=k)
        cached = cached_result(snapshot.cached, snapshot.candidates, k)
        return cached if cached is not None else snapshot.candidates[:k]
    if model == "als" and als is None:
        raise HTTPException(status_code=503, detail="ALS-модель цього домену не завантажено")
    history = load_history(db, user.id, domain)
    ranked = recommend(db, history, domain, model, als, k)
    if not ranked:
        return []
    items = {item.id: item for item in db.scalars(select(Item).options(defer(Item.embedding)).where(
        Item.id.in_([row.item_id for row in ranked]), Item.domain == domain,
    ))}
    return [RecommendationItem(item=ItemSummary.model_validate(items[row.item_id]), score=row.score,
                               sources=RecommendationSources(als=row.als, content=row.content,
                                                             popular=row.popular))
            for row in ranked if row.item_id in items]


async def _explain(
    request: Request, db: Db, user_id: int, domain: Domain, settings: Settings,
) -> list[RecommendationItem]:
    async def snapshot() -> ExplanationSnapshot:
        return await run_in_threadpool(
            prepare_explanation, db, user_id, domain, request.app.state.als_models.get(domain),
            settings.llm_model,
        )

    prepared = await snapshot()
    cached = cached_result(prepared.cached, prepared.candidates, 10)
    if cached is not None or not prepared.candidates:
        return cached if cached is not None else []
    # Release the read transaction before awaiting a slow external model.
    await run_in_threadpool(db.rollback)
    choices = await rerank(request.app.state.ollama, prepared.messages,
                           min(30, len(prepared.candidates)), settings.llm_model)
    current = await snapshot()
    cached = cached_result(current.cached, current.candidates, 10)
    if cached is not None:
        return cached
    if current.profile_hash != prepared.profile_hash:
        return current.candidates[:10]
    result = merge_choices(current.candidates, choices)
    if any(row.explanation is not None for row in result):
        await run_in_threadpool(
            save_explanations, db, user_id, domain, current.profile_hash, result,
        )
    return result


@router.post("/explain", response_model=list[RecommendationItem])
async def explain(
    payload: ExplainRequest, request: Request, db: Db, user: CurrentUser, settings: SettingsDep,
) -> list[RecommendationItem]:
    user_id = user.id
    await run_in_threadpool(db.rollback)
    key = (user_id, payload.domain)
    lock = request.app.state.llm_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        request.app.state.llm_locks[key] = lock
    try:
        async with asyncio.timeout(EXPLANATION_TIMEOUT_SECONDS):
            async with lock:
                return await _explain(request, db, user_id, payload.domain, settings)
    except TimeoutError:
        logger.warning("Перевищено бюджет пояснення LLM; повертаємо гібрид")
        current = await run_in_threadpool(
            prepare_explanation, db, user_id, payload.domain,
            request.app.state.als_models.get(payload.domain), settings.llm_model,
        )
        cached = cached_result(current.cached, current.candidates, 10)
        return cached if cached is not None else current.candidates[:10]
