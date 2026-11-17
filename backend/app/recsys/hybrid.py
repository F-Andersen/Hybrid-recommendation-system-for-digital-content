"""Adaptive weighted fusion, RRF and popularity fallback."""

import math
from dataclasses import dataclass
from typing import Literal

from app.recsys.types import Recommender, UserHistory, history_ids, positive_confidence


@dataclass(frozen=True)
class HybridCandidate:
    item_id: int
    score: float
    als: float = 0.0
    content: float = 0.0
    popular: float = 0.0


def normalize_scores(ranked: list[tuple[int, float]]) -> dict[int, float]:
    scores: dict[int, float] = {}
    for item, score in ranked:
        if not math.isfinite(score):
            raise ValueError("Оцінки рекомендацій мають бути скінченними")
        scores[item] = max(scores.get(item, -math.inf), score)
    if not scores:
        return {}
    low, high = min(scores.values()), max(scores.values())
    return {item: (score - low) / (high - low) if high > low else 1.0
            for item, score in scores.items()}


def weighted_fusion(
    als: list[tuple[int, float]], content: list[tuple[int, float]], alpha: float,
) -> list[HybridCandidate]:
    if not math.isfinite(alpha) or not 0 <= alpha <= 1:
        raise ValueError("Вага alpha має бути у межах [0, 1]")
    als_scores, content_scores = normalize_scores(als), normalize_scores(content)
    result = []
    for item in als_scores.keys() | content_scores.keys():
        first, second = alpha * als_scores.get(item, 0), (1 - alpha) * content_scores.get(item, 0)
        result.append(HybridCandidate(item, first + second, first, second))
    return sorted(result, key=lambda row: (-row.score, row.item_id))


def rrf_fusion(
    als: list[tuple[int, float]], content: list[tuple[int, float]], constant: int = 60,
) -> list[HybridCandidate]:
    if constant < 1:
        raise ValueError("Константа RRF має бути додатною")
    contributions = []
    for ranked in (als, content):
        unique = dict.fromkeys(item for item, _ in ranked)
        contributions.append({item: 1 / (constant + rank)
                              for rank, item in enumerate(unique, start=1)})
    first, second = contributions
    return sorted([
        HybridCandidate(item, first.get(item, 0) + second.get(item, 0),
                        first.get(item, 0), second.get(item, 0))
        for item in first.keys() | second.keys()
    ], key=lambda row: (-row.score, row.item_id))


class HybridRecommender:
    def __init__(
        self, als: Recommender | None, content: Recommender, popular: Recommender,
        item_ids: set[int], *, alpha_max: float = 0.7, n_full: int = 20,
        candidate_count: int = 200, method: Literal["weighted", "rrf"] = "weighted",
    ) -> None:
        if not math.isfinite(alpha_max) or not 0 <= alpha_max <= 1:
            raise ValueError("alpha_max має бути у межах [0, 1]")
        if n_full < 1 or candidate_count < 1 or method not in ("weighted", "rrf"):
            raise ValueError("Некоректні параметри гібрида")
        self.als, self.content, self.popular, self.item_ids = als, content, popular, item_ids
        self.alpha_max, self.n_full = alpha_max, n_full
        self.candidate_count, self.method = candidate_count, method

    def recommend_detailed(
        self, user: UserHistory, k: int, exclude: set[int],
    ) -> list[HybridCandidate]:
        if k <= 0:
            return []
        blocked = exclude | history_ids(user)
        positives = {rating.item_id: positive_confidence(rating)
                     for rating in user.ratings if rating.item_id in self.item_ids}
        n = sum(value > 0 for value in positives.values())
        alpha = self.alpha_max * min(1, n / self.n_full)
        count = max(k, self.candidate_count)

        def candidates(model: Recommender) -> list[tuple[int, float]]:
            return [(item, score) for item, score in model.recommend(user, count, blocked)
                    if item in self.item_ids and item not in blocked]

        content = candidates(self.content)
        als = candidates(self.als) if self.als is not None and alpha > 0 else []
        if not als and not content:
            popular = normalize_scores(candidates(self.popular))
            return sorted([HybridCandidate(item, score, popular=score)
                           for item, score in popular.items()],
                          key=lambda row: (-row.score, row.item_id))[:k]
        if self.method == "rrf":
            return rrf_fusion(als, content)[:k]
        return weighted_fusion(als, content, alpha if als else 0)[:k]

    def recommend(
        self, user: UserHistory, k: int, exclude: set[int],
    ) -> list[tuple[int, float]]:
        return [(row.item_id, row.score) for row in self.recommend_detailed(user, k, exclude)]
