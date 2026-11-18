from datetime import UTC, datetime, timedelta

from app.recsys.splits import Interaction
from app.recsys.types import UserHistory
from scripts.evaluate import CachedRecommender, markdown_table, metric_rows, truncate_histories
from tests.test_splits import rows as make_rows


def test_truncate_keeps_latest_for_temporal():
    data = make_rows(1, 8) + make_rows(2, 3)
    short = truncate_histories(data, 5, temporal=True)
    assert [r.item_id for r in short if r.user_id == 1] == [103, 104, 105, 106, 107]
    assert len([r for r in short if r.user_id == 2]) == 3


def test_truncate_random_is_seeded():
    data = [Interaction(1, 100 + i, 9, False) for i in range(20)]
    first = truncate_histories(data, 5, temporal=False)
    assert first == truncate_histories(list(reversed(data)), 5, temporal=False)
    assert len(first) == 5 and len({r.item_id for r in first}) == 5


class Counting:
    def __init__(self) -> None:
        self.calls = 0

    def recommend(self, user, k, exclude):
        self.calls += 1
        return [(1, 1.0)]


def test_cached_recommender_calls_base_once_per_user_and_k():
    base = Counting()
    cached = CachedRecommender(base)
    user = UserHistory(user_id=7)
    for _ in range(3):
        cached.recommend(user, 10, set())
    cached.recommend(user, 20, set())
    assert base.calls == 2


def test_report_rows_and_table():
    from app.recsys.splits import build_cases

    t0 = datetime(2020, 1, 1, tzinfo=UTC)
    train = [Interaction(1, 10 + i, 9, False, t0 + timedelta(days=i)) for i in range(4)]
    cases = build_cases(train, [Interaction(1, 99, 10, False)])
    rows = metric_rows("als", "all", {1: [99, 5]}, cases, [5])
    assert {(r["metric"], r["value"]) for r in rows} == {
        ("precision", 0.2), ("recall", 1.0), ("ndcg", 1.0)}
    assert "| ALS | 0.2000 | 1.0000 | 1.0000 |" in markdown_table(rows, "all", [5])
