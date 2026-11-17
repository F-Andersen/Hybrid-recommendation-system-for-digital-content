from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import defer

from app.api.deps import CurrentUser, Db
from app.db.models import Item
from app.recsys.types import Domain
from app.schemas.items import ItemSummary
from app.services.recommendations import load_history, load_popularity

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("/items", response_model=list[ItemSummary])
def onboarding_items(
    db: Db, user: CurrentUser, domain: Domain = "movie",
    k: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[ItemSummary]:
    history = load_history(db, user.id, domain)
    ranked = load_popularity(db, domain).recommend(history, max(200, k), set())
    if not ranked:
        return []
    items = {item.id: item for item in db.scalars(select(Item).options(defer(Item.embedding)).where(
        Item.id.in_([item_id for item_id, _ in ranked]),
    ))}
    selected, genres = [], set()
    for item_id, _ in ranked:
        item = items[item_id]
        if not selected or set(item.genres) - genres:
            selected.append(item_id)
            genres.update(item.genres)
            if len(selected) == k:
                break
    for item_id, _ in ranked:
        if len(selected) == k:
            break
        if item_id not in selected:
            selected.append(item_id)
    return [ItemSummary.model_validate(items[item_id]) for item_id in selected]
