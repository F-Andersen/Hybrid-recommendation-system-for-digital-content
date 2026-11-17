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


class Recommender(Protocol):
    def recommend(
        self, user: UserHistory, k: int, exclude: set[int],
    ) -> list[tuple[int, float]]: ...
