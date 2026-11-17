import json

import numpy as np
import pytest

from app.recsys.als import (
    AlsParameters,
    build_interaction_matrix,
    load_available_models,
    load_model,
    save_model,
)
from app.recsys.popularity import PopularityRecommender
from app.recsys.types import HistoryRating, UserHistory


def test_confidence_matrix_orientation_and_duplicate_handling():
    matrix = build_interaction_matrix([10, 20], [100, 200, 300], [
        (10, HistoryRating(100, 10)), (10, HistoryRating(200, None, True)),
        (20, HistoryRating(100, 5)), (20, HistoryRating(300, 6)),
        (10, HistoryRating(100, 8)),
    ])
    assert matrix.shape == (2, 3)
    assert matrix.toarray() == pytest.approx(np.array([[4.2, 1, 0], [0, 0, 3.4]]))


def test_als_excludes_all_rated_viewed_and_explicitly_blocked_items(small_als):
    model, ratings = small_als
    history = UserHistory([rating for user, rating in ratings if user == 100], [1008], user_id=100)
    result = model.recommend(history, 100, {1009})
    blocked = {rating.item_id for rating in history.ratings} | {1008, 1009}
    assert result
    assert not blocked & {item for item, _ in result}
    assert all(item < 1020 for item, _ in result)  # No evidence for the last ten catalog items.
    assert all(np.isfinite(score) for _, score in result)
    assert len(result) == len({item for item, _ in result})


def test_new_user_with_five_ratings_gets_fold_in_without_mutating_model(small_als):
    model, _ = small_als
    before = model.model.user_factors.copy()
    history = UserHistory([HistoryRating(item, 9) for item in range(1000, 1005)])
    result = model.recommend(history, 10, set())
    assert len(result) == 10
    assert not set(range(1000, 1005)) & {item for item, _ in result}
    np.testing.assert_array_equal(before, model.model.user_factors)


def test_known_user_uses_fold_in_when_history_changes(small_als, monkeypatch):
    model, ratings = small_als
    original = model.model.recommend
    modes = []

    def recommend(*args, **kwargs):
        modes.append(kwargs["recalculate_user"])
        return original(*args, **kwargs)

    monkeypatch.setattr(model.model, "recommend", recommend)
    history = UserHistory([rating for user, rating in ratings if user == 100], user_id=100)
    assert model.recommend(history, 10, set())
    history.ratings.append(HistoryRating(1007, 10))
    assert model.recommend(history, 10, set())
    assert modes == [False, True]


def test_als_empty_negative_and_unknown_histories_return_empty(small_als):
    model, _ = small_als
    for history in (UserHistory(), UserHistory([HistoryRating(1000, 1)]),
                    UserHistory([HistoryRating(99999, 10)])):
        assert model.recommend(history, 10, set()) == []
    positive = UserHistory([HistoryRating(1000, 10)])
    assert model.recommend(positive, 0, set()) == []
    assert model.recommend(positive, 10, set(model.item_ids)) == []


def test_artifact_round_trip_and_corrupt_pair_rejection(small_als, tmp_path):
    model, _ = small_als
    save_model(model, tmp_path, "movie")
    restored = load_model(tmp_path, "movie")
    history = UserHistory([HistoryRating(item, 8) for item in range(1000, 1005)])
    assert restored.recommend(history, 10, set()) == model.recommend(history, 10, set())
    assert (restored.user_items != model.user_items).nnz == 0
    assert restored.parameters == model.parameters
    maps = tmp_path / "als_movie_maps.json"
    metadata = json.loads(maps.read_text())
    metadata["artifact_id"] = "different-generation"
    maps.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="Метадані"):
        load_model(tmp_path, "movie")
    assert load_available_models(tmp_path) == {}
    with pytest.raises(ValueError, match="movie"):
        load_available_models(tmp_path, strict=True)


def test_corrupted_npz_is_rejected_before_loading(small_als, tmp_path):
    model, _ = small_als
    save_model(model, tmp_path, "book")
    (tmp_path / "als_book.npz").write_bytes(b"truncated")
    with pytest.raises(ValueError, match="пошкоджені"):
        load_model(tmp_path, "book")


def test_id_maps_are_bound_to_protected_factor_arrays(small_als, tmp_path):
    model, _ = small_als
    save_model(model, tmp_path, "movie")
    path = tmp_path / "als_movie_maps.json"
    metadata = json.loads(path.read_text())
    metadata["item_ids"][-1] = 999999
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="Метадані"):
        load_model(tmp_path, "movie")


def test_popularity_counts_unique_positive_training_pairs():
    model = PopularityRecommender([10, 20, 30, 40], [
        (1, HistoryRating(10, 9)), (1, HistoryRating(10, 8)),
        (2, HistoryRating(10, None, True)), (1, HistoryRating(20, 4)),
        (1, HistoryRating(30, 10)), (1, HistoryRating(30, 2)),
    ])
    assert model.recommend(UserHistory(), 4, set()) == [(10, 2.0), (20, 0.0), (30, 0.0), (40, 0.0)]
    assert model.recommend(UserHistory(views=[10]), 2, {20}) == [(30, 0.0), (40, 0.0)]


@pytest.mark.parametrize("params", [
    {"factors": 0}, {"iterations": -1}, {"regularization": 0},
    {"regularization": float("nan")}, {"num_threads": 0}, {"random_state": -1},
])
def test_invalid_training_parameters_are_rejected(params):
    with pytest.raises(ValueError):
        AlsParameters(**params)
