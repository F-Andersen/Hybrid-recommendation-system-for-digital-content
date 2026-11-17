from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import defer

from app.api.deps import CurrentUser, Db
from app.db.models import Interaction, Item, Rating
from app.recsys.types import Domain
from app.schemas.activity import HistoryItem, HistoryPage, RatedItem, RatingsPage
from app.schemas.items import ItemSummary

router = APIRouter(prefix="/me", tags=["profile"])


@router.get("/ratings", response_model=RatingsPage)
def my_ratings(
    db: Db, user: CurrentUser, domain: Domain | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
) -> RatingsPage:
    filters = [Rating.user_id == user.id, Rating.implicit.is_(False)]
    if domain:
        filters.append(Item.domain == domain)
    total = db.scalar(select(func.count()).select_from(Rating).join(Item).where(*filters)) or 0
    rows = db.execute(select(Rating, Item).join(Item).options(defer(Item.embedding)).where(
        *filters,
    ).order_by(Rating.rated_at.desc().nulls_last(), Rating.item_id.desc()).offset(
        (page - 1) * page_size,
    ).limit(page_size)).all()
    return RatingsPage(items=[RatedItem(item=ItemSummary.model_validate(item), value=rating.value,
                                        rated_at=rating.rated_at) for rating, item in rows],
                       total=total, page=page, page_size=page_size)


@router.get("/history", response_model=HistoryPage)
def my_history(
    db: Db, user: CurrentUser, domain: Domain | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
) -> HistoryPage:
    filters = [Interaction.user_id == user.id]
    if domain:
        filters.append(Item.domain == domain)
    total = db.scalar(select(func.count()).select_from(Interaction).join(Item).where(*filters)) or 0
    rows = db.execute(select(Interaction, Item).join(Item).options(defer(Item.embedding)).where(
        *filters,
    ).order_by(Interaction.created_at.desc(), Interaction.id.desc()).offset(
        (page - 1) * page_size,
    ).limit(page_size)).all()
    return HistoryPage(items=[HistoryItem(id=view.id, item=ItemSummary.model_validate(item),
                                          kind=view.kind, created_at=view.created_at)
                              for view, item in rows], total=total, page=page, page_size=page_size)
