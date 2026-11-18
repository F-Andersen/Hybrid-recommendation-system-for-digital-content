"""Per-user train/validation/test splits and evaluation cases for offline experiments."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from app.recsys.types import HistoryRating, UserHistory

RELEVANCE_THRESHOLD = 8  # >= 4 of 5 stars on MovieLens, >= 8 of 10 on Book-Crossing


@dataclass(frozen=True)
class Interaction:
    user_id: int
    item_id: int
    value: int | None
    implicit: bool
    rated_at: datetime | None = None

    def as_rating(self) -> HistoryRating:
        return HistoryRating(self.item_id, self.value, self.implicit)

    @property
    def relevant(self) -> bool:
        """Only explicit high ratings count as relevant; implicit feedback is train-only."""
        return not self.implicit and self.value is not None and self.value >= RELEVANCE_THRESHOLD


@dataclass
class Split:
    method: str
    train: list[Interaction] = field(default_factory=list)
    validation: list[Interaction] = field(default_factory=list)
    test: list[Interaction] = field(default_factory=list)

    def stats(self) -> dict[str, int | str]:
        return {
            "method": self.method,
            "train": len(self.train), "validation": len(self.validation), "test": len(self.test),
            "users": len({row.user_id for row in self.train + self.validation + self.test}),
        }


def holdout_size(n: int, fraction: float) -> int:
    """Interactions held out per user for each of validation and test."""
    if not 0 < fraction < 0.5:
        raise ValueError("Частка відкладених взаємодій має бути в межах (0, 0.5)")
    if n < 3:
        return 0  # too short to split: everything stays in training
    return max(1, round(n * fraction))


def group_by_user(interactions: Iterable[Interaction]) -> dict[int, list[Interaction]]:
    groups: dict[int, list[Interaction]] = defaultdict(list)
    seen: set[tuple[int, int]] = set()
    for row in interactions:
        key = row.user_id, row.item_id
        if key in seen:
            raise ValueError("Повторна взаємодія користувача з тим самим об'єктом")
        seen.add(key)
        groups[row.user_id].append(row)
    return groups


def _assign(split: Split, rows: list[Interaction], fraction: float) -> None:
    size = holdout_size(len(rows), fraction)
    test_start = len(rows) - size
    validation_start = test_start - size
    split.train.extend(rows[:validation_start])
    split.validation.extend(rows[validation_start:test_start])
    split.test.extend(rows[test_start:])


def temporal_split(interactions: Iterable[Interaction], fraction: float = 0.1) -> Split:
    """Per user: the latest `fraction` is test, the preceding `fraction` is validation."""
    split = Split("temporal")
    for user_id, rows in sorted(group_by_user(interactions).items()):
        if any(row.rated_at is None for row in rows):
            raise ValueError(f"Користувач {user_id}: часове розбиття потребує дат оцінок")
        _assign(split, sorted(rows, key=lambda row: (row.rated_at, row.item_id)), fraction)
    return split


def random_split(
    interactions: Iterable[Interaction], fraction: float = 0.1, seed: int = 42,
) -> Split:
    """Per user, a seeded shuffle; deterministic for the same input regardless of its order."""
    rng = np.random.default_rng(seed)
    split = Split("random")
    for _, rows in sorted(group_by_user(interactions).items()):
        ordered = sorted(rows, key=lambda row: row.item_id)
        _assign(split, [ordered[index] for index in rng.permutation(len(ordered))], fraction)
    return split


@dataclass(frozen=True)
class EvalCase:
    history: UserHistory
    relevant: frozenset[int]

    @property
    def user_id(self) -> int:
        assert self.history.user_id is not None
        return self.history.user_id

    @property
    def train_size(self) -> int:
        return len(self.history.ratings)


def build_histories(train: Iterable[Interaction]) -> dict[int, UserHistory]:
    histories: dict[int, UserHistory] = {}
    for user_id, rows in group_by_user(train).items():
        ratings = [row.as_rating() for row in sorted(rows, key=lambda row: row.item_id)]
        histories[user_id] = UserHistory(ratings, [], user_id=user_id)
    return histories


def build_cases(
    train: Iterable[Interaction], holdout: Iterable[Interaction], *, min_train: int = 3,
) -> list[EvalCase]:
    """Users with >= 1 relevant held-out item and >= `min_train` training interactions."""
    histories = build_histories(train)
    relevant: dict[int, set[int]] = defaultdict(set)
    for row in holdout:
        if row.relevant:
            relevant[row.user_id].add(row.item_id)
    cases = []
    for user_id in sorted(relevant):
        history = histories.get(user_id)
        if history is None or len(history.ratings) < min_train:
            continue
        overlap = relevant[user_id] & {rating.item_id for rating in history.ratings}
        if overlap:
            raise ValueError("Відкладені об'єкти перетинаються з навчальною історією")
        cases.append(EvalCase(history, frozenset(relevant[user_id])))
    return cases
