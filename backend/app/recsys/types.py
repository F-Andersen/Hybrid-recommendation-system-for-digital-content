"""Model inputs shared by the online API and offline experiments."""

from dataclasses import dataclass, field
from typing import Literal, Protocol

Domain = Literal["movie", "book"]


@dataclass(frozen=True)
class HistoryRating:
    item_id: int
    value: int | None
    implicit: bool = False


@dataclass
class UserHistory:
    ratings: list[HistoryRating] = field(default_factory=list)
    views: list[int] = field(default_factory=list)
    user_id: int | None = None


def history_ids(user: UserHistory) -> set[int]:
    return {rating.item_id for rating in user.ratings} | set(user.views)


def positive_confidence(rating: HistoryRating) -> float:
    if rating.implicit:
        if rating.value is not None:
            raise ValueError("Неявна взаємодія не повинна містити явну оцінку")
        return 1.0
    if rating.value is None or not 1 <= rating.value <= 10:
        raise ValueError("Явна оцінка має бути у шкалі 1–10")
    return 1 + 4 * rating.value / 10 if rating.value >= 6 else 0.0


class Recommender(Protocol):
    def recommend(
        self, user: UserHistory, k: int, exclude: set[int],
    ) -> list[tuple[int, float]]: ...
