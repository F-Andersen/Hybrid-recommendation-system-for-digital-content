from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import defer

from app.api.deps import CurrentUser, Db
from app.db.models import Item
from app.recsys.types import Domain
from app.schemas.items import ItemSummary
from app.schemas.recommendations import RecommendationItem, RecommendationSources
from app.services.recommendations import ModelName, load_history, recommend

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("", response_model=list[RecommendationItem])
def recommendations(
    request: Request, db: Db, user: CurrentUser, domain: Domain = "movie",
    model: ModelName = "hybrid", k: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[RecommendationItem]:
    als = request.app.state.als_models.get(domain)
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
