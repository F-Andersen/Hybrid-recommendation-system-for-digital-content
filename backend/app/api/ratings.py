from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, defer

from app.api.deps import CurrentUser, Db
from app.db.models import Item, LlmCache, Rating
from app.schemas.activity import RatingInput, RatingResult

router = APIRouter(prefix="/ratings", tags=["ratings"])


def lock_item(db: Session, item_id: int) -> Item:
    item = db.scalar(select(Item).options(defer(Item.embedding)).where(
        Item.id == item_id,
    ).with_for_update())
    if item is None:
        raise HTTPException(status_code=404, detail="Об'єкт не знайдено")
    return item


def refresh_item_stats(db: Session, item: Item, user_id: int) -> None:
    count, average = db.execute(select(func.count(), func.avg(Rating.value)).where(
        Rating.item_id == item.id,
    )).one()
    item.rating_count, item.rating_avg = count, float(average or 0)
    db.execute(delete(LlmCache).where(LlmCache.user_id == user_id, LlmCache.domain == item.domain))


@router.put("/{item_id}", response_model=RatingResult)
def rate_item(item_id: int, payload: RatingInput, db: Db, user: CurrentUser) -> RatingResult:
    item = lock_item(db, item_id)
    now = datetime.now(UTC)
    statement = insert(Rating).values(user_id=user.id, item_id=item_id, value=payload.value,
                                      implicit=False, rated_at=now)
    db.execute(statement.on_conflict_do_update(
        index_elements=["user_id", "item_id"],
        set_={"value": payload.value, "implicit": False, "rated_at": now},
    ))
    refresh_item_stats(db, item, user.id)
    db.commit()
    return RatingResult(item_id=item_id, value=payload.value, rated_at=now)


@router.delete("/{item_id}", status_code=204)
def remove_rating(item_id: int, db: Db, user: CurrentUser) -> Response:
    item = lock_item(db, item_id)
    db.execute(delete(Rating).where(Rating.user_id == user.id, Rating.item_id == item_id))
    refresh_item_stats(db, item, user.id)
    db.commit()
    return Response(status_code=204)
