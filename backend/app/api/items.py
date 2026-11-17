from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import Session, defer

from app.api.deps import OptionalUser
from app.db.models import Interaction, Item, LlmCache, Rating
from app.db.session import get_db
from app.recsys.content import SqlContentRecommender
from app.recsys.types import Domain
from app.schemas.items import GenreCount, ItemDetail, ItemPage, ItemSummary, SimilarItem

router = APIRouter(prefix="/items", tags=["items"])
Db = Annotated[Session, Depends(get_db)]


@router.get("", response_model=ItemPage)
def list_items(
    db: Db, domain: Domain = "movie",
    q: Annotated[str | None, Query(max_length=200)] = None,
    genre: Annotated[str | None, Query(max_length=200)] = None,
    sort: Literal["popular", "rating", "year"] = "popular",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
) -> ItemPage:
    conditions = [Item.domain == domain]
    if q and q.strip():
        conditions.append(Item.title.icontains(q.strip(), autoescape=True))
    if genre:
        conditions.append(Item.genres.contains([genre]))
    total = db.scalar(select(func.count()).select_from(Item).where(*conditions)) or 0
    ordering = {
        "popular": [Item.rating_count.desc(), Item.rating_avg.desc()],
        "rating": [Item.rating_avg.desc(), Item.rating_count.desc()],
        "year": [Item.year.desc().nulls_last(), Item.rating_count.desc()],
    }[sort]
    items = db.scalars(select(Item).options(defer(Item.embedding)).where(*conditions).order_by(
        *ordering, Item.id,
    ).offset(
        (page - 1) * page_size,
    ).limit(page_size)).all()
    return ItemPage(items=[ItemSummary.model_validate(item) for item in items], total=total,
                    page=page, page_size=page_size)


# Static paths must precede /{item_id}.
@router.get("/genres", response_model=list[GenreCount])
def list_genres(db: Db, domain: Domain = "movie") -> list[GenreCount]:
    genres = select(Item.id.label("item_id"), func.unnest(Item.genres).label("genre")).where(
        Item.domain == domain,
    ).subquery()
    count = func.count(distinct(genres.c.item_id))
    rows = db.execute(select(genres.c.genre, count).group_by(genres.c.genre).order_by(
        count.desc(), genres.c.genre,
    )).all()
    return [GenreCount(genre=genre, count=n) for genre, n in rows]


def get_item_or_404(db: Session, item_id: int, *, with_embedding: bool = False) -> Item:
    item = db.get(Item, item_id, options=[] if with_embedding else [defer(Item.embedding)])
    if item is None:
        raise HTTPException(status_code=404, detail="Об'єкт не знайдено")
    return item


@router.get("/{item_id}", response_model=ItemDetail)
def get_item(item_id: int, db: Db, user: OptionalUser) -> ItemDetail:
    item = get_item_or_404(db, item_id)
    result = ItemDetail.model_validate(item)
    if user is not None:
        result.my_rating = db.scalar(select(Rating.value).where(
            Rating.user_id == user.id, Rating.item_id == item_id,
        ))
        db.add(Interaction(user_id=user.id, item_id=item_id, kind="view"))
        db.execute(delete(LlmCache).where(
            LlmCache.user_id == user.id, LlmCache.domain == item.domain,
        ))
        db.commit()
    return result


@router.get("/{item_id}/similar", response_model=list[SimilarItem])
def similar_items(item_id: int, db: Db) -> list[SimilarItem]:
    item = get_item_or_404(db, item_id, with_embedding=True)
    if item.embedding is None:
        return []
    ranked = SqlContentRecommender(db, item.domain).rank_vector(item.embedding, 12, {item_id})
    if not ranked:
        return []
    candidates = {candidate.id: candidate for candidate in db.scalars(select(Item).options(
        defer(Item.embedding),
    ).where(
        Item.id.in_([value for value, _ in ranked]),
    ))}
    return [SimilarItem(item=ItemSummary.model_validate(candidates[value]), score=score)
            for value, score in ranked]
