import math

import pytest

from app.recsys.metrics import (
    catalog_coverage,
    evaluate_rankings,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def test_precision_and_recall_hand_example():
    ranked = [1, 2, 3, 4, 5]
    relevant = {2, 5, 9}
    assert precision_at_k(ranked, relevant, 5) == pytest.approx(2 / 5)
    assert precision_at_k(ranked, relevant, 2) == pytest.approx(1 / 2)
    assert recall_at_k(ranked, relevant, 5) == pytest.approx(2 / 3)
    assert recall_at_k(ranked, relevant, 1) == 0


def test_short_list_is_not_rewarded_in_precision():
    assert precision_at_k([7], {7}, 10) == pytest.approx(0.1)


def test_ndcg_hand_example():
    # hits at positions 2 and 4; 3 relevant items, k = 4
    dcg = 1 / math.log2(3) + 1 / math.log2(5)
    idcg = 1 + 1 / math.log2(3) + 1 / math.log2(4)
    assert ndcg_at_k([10, 2, 11, 5], {2, 5, 9}, 4) == pytest.approx(dcg / idcg)


def test_ndcg_perfect_and_empty():
    assert ndcg_at_k([3, 1, 2], {1, 2, 3}, 3) == pytest.approx(1.0)
    assert ndcg_at_k([3, 1], {1, 3}, 10) == pytest.approx(1.0)  # IDCG uses min(k, |rel|)
    assert ndcg_at_k([], {1}, 5) == 0


def test_duplicates_count_once():
    assert precision_at_k([1, 1, 1], {1}, 3) == pytest.approx(1 / 3)
    assert ndcg_at_k([1, 1, 2], {1, 2}, 2) == pytest.approx(1.0)


def test_invalid_inputs():
    with pytest.raises(ValueError):
        precision_at_k([1], {1}, 0)
    with pytest.raises(ValueError):
        recall_at_k([1], set(), 5)
    with pytest.raises(ValueError):
        ndcg_at_k([1], set(), 5)


def test_evaluate_rankings_averages_and_missing_user_scores_zero():
    result = evaluate_rankings({1: [5, 6]}, {1: {5}, 2: {9}}, [1, 2])
    assert result["precision"][1] == pytest.approx(0.5)
    assert result["precision"][2] == pytest.approx(0.25)
    assert result["recall"][2] == pytest.approx(0.5)
    assert result["ndcg"][1] == pytest.approx(0.5)


def test_catalog_coverage():
    assert catalog_coverage([[1, 2, 3], [3, 4, 5]], 10, 2) == pytest.approx(4 / 10)
    with pytest.raises(ValueError):
        catalog_coverage([], 0, 1)
