"""Top-K ranking metrics with binary relevance, averaged over users."""

import math
from collections.abc import Collection, Iterable, Mapping, Sequence


def _check(k: int) -> None:
    if k < 1:
        raise ValueError("K має бути додатним")


def _hits(ranked: Sequence[int], relevant: Collection[int], k: int) -> list[bool]:
    """Relevance flags for the first k distinct items (duplicates never count twice)."""
    seen: set[int] = set()
    flags = []
    for item in ranked:
        if item in seen:
            continue
        seen.add(item)
        flags.append(item in relevant)
        if len(flags) == k:
            break
    return flags


def precision_at_k(ranked: Sequence[int], relevant: Collection[int], k: int) -> float:
    """Hits in the top-k divided by k (a short list is not rewarded)."""
    _check(k)
    return sum(_hits(ranked, relevant, k)) / k


def recall_at_k(ranked: Sequence[int], relevant: Collection[int], k: int) -> float:
    _check(k)
    if not relevant:
        raise ValueError("Recall не визначений без релевантних об'єктів")
    return sum(_hits(ranked, relevant, k)) / len(relevant)


def ndcg_at_k(ranked: Sequence[int], relevant: Collection[int], k: int) -> float:
    """DCG = sum rel_i / log2(i + 1) for positions i = 1..k; IDCG puts min(k, |rel|) hits first."""
    _check(k)
    if not relevant:
        raise ValueError("NDCG не визначений без релевантних об'єктів")
    dcg = sum(1 / math.log2(position + 2)
              for position, hit in enumerate(_hits(ranked, relevant, k)) if hit)
    ideal = sum(1 / math.log2(position + 2) for position in range(min(k, len(relevant))))
    return dcg / ideal


METRICS = {"precision": precision_at_k, "recall": recall_at_k, "ndcg": ndcg_at_k}


def evaluate_rankings(
    rankings: Mapping[int, Sequence[int]], relevant: Mapping[int, Collection[int]],
    ks: Iterable[int],
) -> dict[str, dict[int, float]]:
    """Mean of each metric over the users in `relevant`; a missing ranking scores zero."""
    if not relevant:
        raise ValueError("Немає користувачів для оцінювання")
    ks = sorted(set(ks))
    result: dict[str, dict[int, float]] = {name: {} for name in METRICS}
    for name, metric in METRICS.items():
        for k in ks:
            total = sum(metric(rankings.get(user, ()), items, k)
                        for user, items in relevant.items())
            result[name][k] = total / len(relevant)
    return result


def catalog_coverage(rankings: Iterable[Sequence[int]], catalog_size: int, k: int) -> float:
    """Share of the catalog that appears at least once in somebody's top-k."""
    _check(k)
    if catalog_size < 1:
        raise ValueError("Розмір каталогу має бути додатним")
    shown: set[int] = set()
    for ranked in rankings:
        shown.update(list(dict.fromkeys(ranked))[:k])
    return len(shown) / catalog_size
