"""Content text, user profiles, exact NumPy and PostgreSQL cosine ranking."""

from collections.abc import Mapping
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import Item
from app.recsys.types import Domain, UserHistory, history_ids
from app.recsys.vectors import EMBEDDING_DIMENSION, normalize_vectors


class ContentItem(Protocol):
    domain: str
    title: str
    year: int | None
    creators: list[str]
    genres: list[str]
    description: str | None
    meta: dict[str, Any]


def build_item_text(item: ContentItem) -> str:
    meta = item.meta or {}
    lines = [f"Type: {item.domain}", f"Title: {item.title}"]
    if item.year is not None:
        lines.append(f"Year: {item.year}")
    if item.domain == "book":
        if item.creators:
            lines.append("Authors: " + ", ".join(item.creators))
        if meta.get("publisher"):
            lines.append("Publisher: " + str(meta["publisher"]))
    if item.genres:
        lines.append("Genres/subjects: " + ", ".join(item.genres))
    if meta.get("tags"):
        lines.append("Tags: " + ", ".join(meta["tags"]))
    if item.description:
        lines.append("Description: " + item.description[:1500])
    return "\n".join(lines)


def build_user_profile(
    user: UserHistory, embeddings: Mapping[int, NDArray[np.float32]],
) -> NDArray[np.float32] | None:
    profile = np.zeros(EMBEDDING_DIMENSION, dtype=np.float64)
    positive = False
    # One rating per item; a rating supersedes a view of the same item.
    ratings = {rating.item_id: rating for rating in user.ratings}
    weights: dict[int, float] = {item_id: 0.3 for item_id in set(user.views) - ratings.keys()}
    for item_id, rating in ratings.items():
        if rating.implicit:
            weight = 0.3
        elif rating.value is not None and 1 <= rating.value <= 10:
            weight = (rating.value - 5.5) / 4.5
        else:
            raise ValueError("Явна оцінка має бути у шкалі 1–10")
        weights[item_id] = weight
    for item_id, weight in weights.items():
        vector = embeddings.get(item_id)
        if vector is not None:
            profile += weight * vector
            positive |= weight > 0
    norm = np.linalg.norm(profile)
    if not positive or norm < 1e-12:
        return None
    return (profile / norm).astype(np.float32)


class NumpyContentRecommender:
    def __init__(self, item_ids: list[int], embeddings: object) -> None:
        self.item_ids = np.asarray(item_ids, dtype=np.int64)
        self.matrix = normalize_vectors(embeddings, len(item_ids))
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("ID об'єктів мають бути унікальними")
        self.embeddings = dict(zip(item_ids, self.matrix, strict=True))

    def rank_vector(
        self, vector: NDArray[np.float32], k: int, exclude: set[int],
    ) -> list[tuple[int, float]]:
        if k <= 0:
            return []
        normalized = normalize_vectors([vector], 1)[0]
        scores = np.clip(self.matrix @ normalized, -1, 1)
        eligible = ~np.isin(self.item_ids, list(exclude))
        ids, values = self.item_ids[eligible], scores[eligible]
        order = np.lexsort((ids, -values))[:k]
        return [(int(ids[index]), float(values[index])) for index in order]

    def recommend(
        self, user: UserHistory, k: int, exclude: set[int],
    ) -> list[tuple[int, float]]:
        profile = build_user_profile(user, self.embeddings)
        if profile is None:
            return []
        return self.rank_vector(profile, k, exclude | history_ids(user))


class SqlContentRecommender:
    def __init__(self, session: Session, domain: Domain, *, exact: bool = False) -> None:
        self.session, self.domain, self.exact = session, domain, exact

    def rank_vector(
        self, vector: NDArray[np.float32], k: int, exclude: set[int],
    ) -> list[tuple[int, float]]:
        if k <= 0:
            return []
        vector = normalize_vectors([vector], 1)[0]
        distance = Item.embedding.cosine_distance(vector)
        query = select(Item.id, (1 - distance).label("score")).where(
            Item.domain == self.domain, Item.embedding.is_not(None),
        )
        if exclude:
            query = query.where(Item.id.not_in(exclude))
        if self.exact:
            # Disable vector index scans only for this query, then restore the setting.
            previous = self.session.scalar(text("SHOW enable_indexscan"))
            self.session.execute(text("SET LOCAL enable_indexscan = off"))
        else:
            self.session.execute(text("SET LOCAL hnsw.ef_search = 200"))
            self.session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
        try:
            rows = self.session.execute(query.order_by(distance, Item.id).limit(k)).all()
        finally:
            if self.exact:
                self.session.execute(
                    text("SELECT set_config('enable_indexscan', :value, true)"),
                    {"value": previous},
                )
        return [(item_id, float(np.clip(score, -1, 1))) for item_id, score in rows]

    def recommend(
        self, user: UserHistory, k: int, exclude: set[int],
    ) -> list[tuple[int, float]]:
        ids = history_ids(user)
        if not ids:
            return []
        rows = self.session.execute(select(Item.id, Item.embedding).where(
            Item.id.in_(ids), Item.embedding.is_not(None),
        )).all()
        profile = build_user_profile(user, {
            item_id: np.asarray(vector, dtype=np.float32) for item_id, vector in rows
        })
        if profile is None:
            return []
        return self.rank_vector(profile, k, exclude | ids)
