import pytest

from app.recsys.hybrid import HybridRecommender, normalize_scores, rrf_fusion, weighted_fusion
from app.recsys.types import HistoryRating, UserHistory


class FixedRecommender:
    def __init__(self, ranked):
        self.ranked = ranked
        self.calls = 0

    def recommend(self, user, k, exclude):
        self.calls += 1
        return [(item, score) for item, score in self.ranked if item not in exclude][:k]


def test_normalization_and_weighted_fusion():
    assert normalize_scores([(1, -1), (2, 0), (3, 1)]) == {1: 0, 2: 0.5, 3: 1}
    assert normalize_scores([(1, 5), (2, 5)]) == {1: 1, 2: 1}
    result = weighted_fusion([(2, 3), (4, 1)], [(1, 1), (2, 0.5), (3, 0)], 0.25)
    assert [(row.item_id, row.score) for row in result] == [(1, 0.75), (2, 0.625), (3, 0), (4, 0)]
    assert all(row.score == row.als + row.content for row in result)


def test_rrf_combines_positions_and_deduplicates():
    result = rrf_fusion([(2, 100), (2, 99), (3, 10)], [(1, 0.9), (2, 0.1)])
    assert [row.item_id for row in result] == [2, 1, 3]
    assert result[0].score == pytest.approx(1 / 61 + 1 / 62)


def test_no_positive_ratings_reduces_to_normalized_content():
    content = FixedRecommender([(1, 0.9), (2, 0.4), (3, -0.2)])
    als = FixedRecommender([(4, 1)])
    model = HybridRecommender(als, content, FixedRecommender([]), {1, 2, 3, 4})
    result = model.recommend(UserHistory(views=[99]), 3, set())
    assert [item for item, _ in result] == [1, 2, 3]
    assert dict(result) == pytest.approx(normalize_scores(content.ranked))
    assert all(0 <= score <= 1 for _, score in result)
    assert als.calls == 0


@pytest.mark.parametrize(("count", "alpha"), [(5, 0.175), (20, 0.7), (30, 0.7)])
def test_adaptive_weight_and_contributions(count, alpha):
    history = UserHistory([HistoryRating(item, 10) for item in range(100, 100 + count)])
    model = HybridRecommender(
        FixedRecommender([(2, 3), (4, 1)]), FixedRecommender([(1, 1), (2, 0.5), (3, 0)]),
        FixedRecommender([]), set(range(1, 5)) | set(range(100, 140)),
    )
    result = {row.item_id: row for row in model.recommend_detailed(history, 4, set())}
    assert result[2].als == pytest.approx(alpha)
    assert result[2].content == pytest.approx((1 - alpha) * 0.5)
    assert all(0 <= row.score <= 1 for row in result.values())


def test_popularity_fallback_and_exclusions():
    popular = FixedRecommender([(1, 10), (2, 8), (3, 4), (999, 1)])
    model = HybridRecommender(None, FixedRecommender([]), popular, {1, 2, 3})
    result = model.recommend_detailed(UserHistory(views=[1]), 10, {2})
    assert [(row.item_id, row.score) for row in result] == [(3, 1)]
    assert result[0].popular == 1
    assert model.recommend(UserHistory(), 0, set()) == []


def test_missing_als_uses_content_and_rrf_is_available():
    content, popular = FixedRecommender([(1, 0.5), (2, 0.2)]), FixedRecommender([])
    history = UserHistory([HistoryRating(100, 10)])
    model = HybridRecommender(None, content, popular, {1, 2, 100})
    assert model.recommend(history, 2, set()) == [(1, 1), (2, 0)]
    rrf = HybridRecommender(FixedRecommender([(2, 100)]), content, popular,
                            {1, 2, 100}, method="rrf")
    assert rrf.recommend(history, 2, set())[0][0] == 2


@pytest.mark.parametrize("params", [{"alpha_max": -1}, {"n_full": 0}, {"candidate_count": 0}])
def test_invalid_hybrid_parameters(params):
    with pytest.raises(ValueError):
        HybridRecommender(None, FixedRecommender([]), FixedRecommender([]), set(), **params)
