"""Popularity based solely on positive feedback in the supplied training data."""

from collections import Counter
from collections.abc import Iterable

from app.recsys.types import HistoryRating, UserHistory, history_ids, positive_confidence


class PopularityRecommender:
    def __init__(
        self, item_ids: Iterable[int], ratings: Iterable[tuple[int, HistoryRating]],
    ) -> None:
        self.item_ids = set(item_ids)
        pairs = {}
        for user_id, rating in ratings:
            if rating.item_id in self.item_ids:
                pairs[user_id, rating.item_id] = bool(positive_confidence(rating))
        self.counts = Counter(item_id for (_, item_id), positive in pairs.items() if positive)

    def recommend(
        self, user: UserHistory, k: int, exclude: set[int],
    ) -> list[tuple[int, float]]:
        if k <= 0:
            return []
        blocked = exclude | history_ids(user)
        ranked = sorted(self.item_ids - blocked, key=lambda item: (-self.counts[item], item))[:k]
        return [(item, float(self.counts[item])) for item in ranked]
