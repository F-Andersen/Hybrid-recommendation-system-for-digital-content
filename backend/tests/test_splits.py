from datetime import UTC, datetime, timedelta

import pytest

from app.recsys.splits import (
    Interaction,
    build_cases,
    holdout_size,
    random_split,
    temporal_split,
)

T0 = datetime(2020, 1, 1, tzinfo=UTC)


def rows(user_id, n, *, value=9, dated=True, implicit=False):
    return [Interaction(user_id, 100 + i, None if implicit else value, implicit,
                        T0 + timedelta(days=i) if dated else None) for i in range(n)]


def test_holdout_size():
    assert holdout_size(2, 0.1) == 0
    assert holdout_size(3, 0.1) == 1
    assert holdout_size(20, 0.1) == 2
    assert holdout_size(25, 0.1) == 2  # banker's rounding of 2.5
    with pytest.raises(ValueError):
        holdout_size(10, 0.6)


def test_temporal_split_keeps_latest_for_test():
    data = rows(1, 20)[::-1]  # input order must not matter
    split = temporal_split(data)
    assert [r.item_id for r in split.test] == [118, 119]
    assert [r.item_id for r in split.validation] == [116, 117]
    assert len(split.train) == 16
    assert max(r.rated_at for r in split.train) < min(r.rated_at for r in split.validation)


def test_temporal_split_requires_dates():
    with pytest.raises(ValueError):
        temporal_split(rows(1, 5, dated=False))


def test_random_split_is_seeded_disjoint_and_order_independent():
    data = rows(1, 30) + rows(2, 4) + rows(3, 2)
    first, second = random_split(data, seed=42), random_split(list(reversed(data)), seed=42)
    assert [r.item_id for r in first.test] == [r.item_id for r in second.test]
    assert random_split(data, seed=7).test != first.test or len(first.test) < 2
    parts = [{(r.user_id, r.item_id) for r in part}
             for part in (first.train, first.validation, first.test)]
    assert not (parts[0] & parts[1]) and not (parts[0] & parts[2]) and not (parts[1] & parts[2])
    assert sum(map(len, parts)) == len(data)
    assert {r.user_id for r in first.test} == {1, 2}  # user 3 is too short to split


def test_duplicates_rejected():
    with pytest.raises(ValueError):
        random_split(rows(1, 3) + rows(1, 1))


def test_build_cases_filters_users():
    train = rows(1, 5) + rows(2, 2) + rows(3, 5)
    holdout = [
        Interaction(1, 900, 9, False), Interaction(1, 901, 5, False),  # one relevant
        Interaction(2, 900, 10, False),  # too little training history
        Interaction(3, 900, None, True),  # implicit is never relevant
    ]
    cases = build_cases(train, holdout)
    assert [c.user_id for c in cases] == [1]
    assert cases[0].relevant == {900}
    assert cases[0].train_size == 5
    assert cases[0].history.views == []
