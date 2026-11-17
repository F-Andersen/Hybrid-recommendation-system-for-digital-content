"""Load current histories and build online recommendations from shared models."""

from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Interaction, Item, Rating
from app.recsys.als import AlsRecommender
from app.recsys.content import SqlContentRecommender
from app.recsys.hybrid import HybridCandidate, HybridRecommender, normalize_scores
from app.recsys.popularity import PopularityRecommender
from app.recsys.types import Domain, HistoryRating, UserHistory, history_ids

ModelName = Literal["hybrid", "als", "content", "popular"]


def load_history(db: Session, user_id: int, domain: Domain) -> UserHistory:
    ratings = db.execute(select(Rating.item_id, Rating.value, Rating.implicit).join(Item).where(
        Rating.user_id == user_id, Item.domain == domain,
    ).order_by(Rating.item_id)).all()
    views = list(db.scalars(select(Interaction.item_id).join(Item).where(
        Interaction.user_id == user_id, Item.domain == domain,
    ).distinct()))
    return UserHistory([HistoryRating(*row) for row in ratings], views, user_id=user_id)


def load_popularity(db: Session, domain: Domain) -> PopularityRecommender:
    positive = func.count(Rating.user_id).filter(Rating.implicit | (Rating.value >= 6))
    counts = dict(db.execute(select(Item.id, positive).outerjoin(
        Rating, Rating.item_id == Item.id,
    ).where(Item.domain == domain).group_by(Item.id)).all())
    return PopularityRecommender.from_counts(counts)


def recommend(
    db: Session, history: UserHistory, domain: Domain, model_name: ModelName,
    als: AlsRecommender | None, k: int,
) -> list[HybridCandidate]:
    popular = load_popularity(db, domain)
    content = SqlContentRecommender(db, domain)
    if model_name == "hybrid":
        return HybridRecommender(als, content, popular, popular.item_ids).recommend_detailed(
            history, k, set(),
        )
    model = {"als": als, "content": content, "popular": popular}[model_name]
    if model is None:
        return []
    ranked = model.recommend(history, max(200, k), history_ids(history))
    scores = normalize_scores([(item, score) for item, score in ranked if item in popular.item_ids])
    return sorted([
        HybridCandidate(item, score, als=score if model_name == "als" else 0,
                        content=score if model_name == "content" else 0,
                        popular=score if model_name == "popular" else 0)
        for item, score in scores.items()
    ], key=lambda row: (-row.score, row.item_id))[:k]
