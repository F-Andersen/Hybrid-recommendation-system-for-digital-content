"""Offline comparison of popularity, content, ALS, hybrid (weighted / RRF) and hybrid + LLM.

Protocol (docs/IMPLEMENTATION.md, section 09):
  * MovieLens: per-user temporal split; Book-Crossing: per-user random split, seed 42.
  * Hyperparameters are chosen by NDCG@10 on validation with models trained on `train` only.
  * Final numbers: models retrained on train + validation, scored once on test.
  * Every model ranks the full domain catalogue minus the user's training history.

Usage:  python -m scripts.evaluate --domain movie [--skip-llm] [--llm-users 200]
"""

import argparse
import asyncio
import csv
import hashlib
import itertools
import json
import logging
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.orm import defer

from app.core.config import get_settings
from app.db.models import Item, Rating, User
from app.db.session import SessionLocal
from app.llm.client import OllamaClient
from app.llm.prompts import PROMPT_VERSION
from app.llm.rerank import RerankChoice, rerank
from app.recsys.als import AlsParameters, AlsRecommender, train_als
from app.recsys.content import NumpyContentRecommender
from app.recsys.hybrid import HybridRecommender
from app.recsys.metrics import catalog_coverage, evaluate_rankings
from app.recsys.popularity import PopularityRecommender
from app.recsys.splits import (
    RELEVANCE_THRESHOLD,
    EvalCase,
    Interaction,
    Split,
    build_cases,
    random_split,
    temporal_split,
)
from app.recsys.types import Domain, Recommender, UserHistory
from app.services.explanations import explanation_messages

SEED = 42
KS = (5, 10, 20)
LLM_KS = (5, 10)
SELECTION_K = 10
COLD_THRESHOLD = 10  # users with fewer training interactions form the cold-start slice
COLD_HISTORY = 5  # simulated cold start: interactions left in each test user's history
EXPLANATION_TIMEOUT_SECONDS = 120  # per-user LLM budget, as in the API
GRIDS: dict[str, dict[str, list[Any]]] = {
    "full": {
        "factors": [32, 64, 128], "regularization": [0.01, 0.05, 0.1], "iterations": [15, 30],
        "alpha_max": [0.3, 0.5, 0.7, 0.9], "n_full": [10, 20, 40],
    },
    "small": {
        "factors": [64], "regularization": [0.05], "iterations": [15],
        "alpha_max": [0.5, 0.7], "n_full": [20],
    },
}
MODEL_LABELS = {
    "popular": "Популярність",
    "content": "Контентна (BGE-M3)",
    "als": "ALS",
    "hybrid_weighted": "Гібрид (зважений)",
    "hybrid_rrf": "Гібрид (RRF)",
    "hybrid_llm": "Гібрид + Qwen3",
}
MODEL_ORDER = list(MODEL_LABELS)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


def log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


# ---------------------------------------------------------------- data


@dataclass
class DomainData:
    domain: Domain
    item_ids: list[int]
    embeddings: np.ndarray
    interactions: list[Interaction]
    items: dict[int, Item]


def load_domain(domain: Domain) -> DomainData:
    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        rows = session.execute(select(Item.id, Item.embedding).where(
            Item.domain == domain, Item.embedding.is_not(None),
        ).order_by(Item.id)).all()
        item_ids = [row.id for row in rows]
        embeddings = np.asarray([row.embedding for row in rows], dtype=np.float32)
        items = {item.id: item for item in session.scalars(
            select(Item).options(defer(Item.embedding)).where(Item.domain == domain),
        )}
        # Dataset users only: accounts created on the platform are not part of the experiment.
        ratings = session.execute(select(
            Rating.user_id, Rating.item_id, Rating.value, Rating.implicit, Rating.rated_at,
        ).join(Item, Item.id == Rating.item_id).join(User, User.id == Rating.user_id).where(
            Item.domain == domain, User.source != "web",
        ).order_by(Rating.user_id, Rating.item_id)).all()
    known = set(item_ids)
    interactions = [Interaction(*row) for row in ratings if row.item_id in known]
    return DomainData(domain, item_ids, embeddings, interactions, items)


def split_domain(data: DomainData) -> Split:
    if data.domain == "movie":
        return temporal_split(data.interactions)
    return random_split(data.interactions, seed=SEED)


# ---------------------------------------------------------------- models


class CachedRecommender:
    """Memoises candidate lists per (user, k) so grid search reuses ALS / content candidates.

    Within one phase a user's exclusion set is always their own training history.
    """

    def __init__(self, base: Recommender) -> None:
        self.base = base
        self.cache: dict[tuple[int | None, int], list[tuple[int, float]]] = {}

    def recommend(self, user: UserHistory, k: int, exclude: set[int]) -> list[tuple[int, float]]:
        key = (user.user_id, k)
        if key not in self.cache:
            self.cache[key] = self.base.recommend(user, k, exclude)
        return self.cache[key]


def fit_als(train: list[Interaction], item_ids: list[int], params: AlsParameters) -> AlsRecommender:
    user_ids = sorted({row.user_id for row in train})
    return train_als(user_ids, item_ids, [(row.user_id, row.as_rating()) for row in train], params)


def build_models(
    popular: PopularityRecommender, als: AlsRecommender, content: NumpyContentRecommender,
    item_set: set[int], hybrid_params: dict[str, Any],
) -> dict[str, Recommender]:
    """Final-phase models sharing one set of per-phase caches."""
    cached_popular, cached_als = CachedRecommender(popular), CachedRecommender(als)
    cached_content = CachedRecommender(content)
    return {
        "popular": cached_popular, "content": cached_content, "als": cached_als,
        "hybrid_weighted": HybridRecommender(cached_als, cached_content, cached_popular,
                                             item_set, **hybrid_params),
        "hybrid_rrf": HybridRecommender(cached_als, cached_content, cached_popular, item_set,
                                        method="rrf"),
    }


def truncate_histories(
    train: list[Interaction], size: int, *, temporal: bool, seed: int = SEED,
) -> list[Interaction]:
    """Keep `size` training interactions per user: the latest ones, or a seeded random subset."""
    groups: dict[int, list[Interaction]] = defaultdict(list)
    for row in train:
        groups[row.user_id].append(row)
    rng = np.random.default_rng(seed)
    result = []
    for user_id in sorted(groups):
        rows = sorted(groups[user_id], key=lambda r: (r.rated_at or datetime.min, r.item_id))
        if temporal:
            result += rows[-size:]
        else:
            picked = rng.permutation(len(rows))[:size]
            result += [rows[i] for i in sorted(picked)]
    return result


def rank(model: Recommender, cases: Sequence[EvalCase], k: int, label: str) -> dict[int, list[int]]:
    started, result = time.perf_counter(), {}
    for index, case in enumerate(cases, start=1):
        result[case.user_id] = [item for item, _ in model.recommend(case.history, k, set())]
        if index % 2000 == 0:
            log(f"  {label}: {index}/{len(cases)}")
    log(f"  {label}: {len(cases)} користувачів за {time.perf_counter() - started:.1f} с")
    return result


def ndcg_at(rankings: dict[int, list[int]], cases: Sequence[EvalCase], k: int) -> float:
    return evaluate_rankings(rankings, {c.user_id: c.relevant for c in cases}, [k])["ndcg"][k]


# ---------------------------------------------------------------- tuning


def tune(
    data: DomainData, split: Split, grid: dict[str, list[Any]], threads: int,
    content: NumpyContentRecommender,
) -> tuple[AlsParameters, dict[str, Any], dict[str, list[dict[str, Any]]]]:
    cases = build_cases(split.train, split.validation)
    log(f"Валідація: {len(cases)} користувачів")
    popular = CachedRecommender(PopularityRecommender(
        data.item_ids, [(r.user_id, r.as_rating()) for r in split.train]))
    report: dict[str, list[dict[str, Any]]] = {"als": [], "hybrid": []}

    best: tuple[float, AlsParameters | None, AlsRecommender | None] = (-1.0, None, None)
    for factors, regularization, iterations in itertools.product(
        grid["factors"], grid["regularization"], grid["iterations"],
    ):
        params = AlsParameters(factors=factors, regularization=regularization,
                               iterations=iterations, random_state=SEED, num_threads=threads)
        model = fit_als(split.train, data.item_ids, params)
        score = ndcg_at(rank(model, cases, SELECTION_K, f"ALS f={factors} λ={regularization} "
                             f"it={iterations}"), cases, SELECTION_K)
        report["als"].append({"factors": factors, "regularization": regularization,
                              "iterations": iterations, "ndcg@10": score})
        log(f"    NDCG@10 = {score:.4f}")
        if score > best[0]:
            best = (score, params, model)
    _, als_params, als_model = best
    assert als_params is not None and als_model is not None

    cached_als, cached_content = CachedRecommender(als_model), CachedRecommender(content)
    item_set = set(data.item_ids)
    best_hybrid: tuple[float, dict[str, Any]] = (-1.0, {})
    for alpha_max, n_full in itertools.product(grid["alpha_max"], grid["n_full"]):
        hybrid = HybridRecommender(cached_als, cached_content, popular, item_set,
                                   alpha_max=alpha_max, n_full=n_full)
        score = ndcg_at(rank(hybrid, cases, SELECTION_K, f"гібрид α={alpha_max} n={n_full}"),
                        cases, SELECTION_K)
        report["hybrid"].append({"alpha_max": alpha_max, "n_full": n_full, "ndcg@10": score})
        log(f"    NDCG@10 = {score:.4f}")
        if score > best_hybrid[0]:
            best_hybrid = (score, {"alpha_max": alpha_max, "n_full": n_full})
    return als_params, best_hybrid[1], report


# ---------------------------------------------------------------- LLM reranking


async def llm_rankings(
    cases: Sequence[EvalCase], hybrid: HybridRecommender, data: DomainData,
    train_counts: dict[int, int], cache_dir: Path,
) -> tuple[dict[int, list[int]], dict[int, list[int]], dict[str, Any]]:
    """Hybrid top-30 -> Qwen3 picks 10 (same prompt and validation as the API)."""
    settings = get_settings()
    cache_dir.mkdir(parents=True, exist_ok=True)
    client = OllamaClient(settings.ollama_base_url)
    llm, base = {}, {}
    stats = Counter[str]()
    latencies: list[float] = []
    try:
        for index, case in enumerate(cases, start=1):
            candidates = [row.item_id for row in hybrid.recommend_detailed(case.history, 30, set())]
            base[case.user_id] = candidates[:10]
            if not candidates:
                llm[case.user_id] = []
                continue
            ratings = [(rating, data.items[rating.item_id]) for rating in case.history.ratings]
            messages = explanation_messages(ratings, [], [data.items[i] for i in candidates],
                                            train_counts)
            key = hashlib.sha256(json.dumps(
                {"model": settings.llm_model, "prompt": PROMPT_VERSION, "messages": messages},
                ensure_ascii=False, sort_keys=True,
            ).encode("utf-8")).hexdigest()
            path = cache_dir / f"{key}.json"
            if path.exists():
                choices = [RerankChoice(**row) for row in json.loads(path.read_text("utf-8"))]
                stats["cache_hits"] += 1
            else:
                started = time.perf_counter()
                try:
                    # Same overall budget as the API; the httpx read timeout alone can hang.
                    async with asyncio.timeout(EXPLANATION_TIMEOUT_SECONDS):
                        choices = await rerank(client, messages, len(candidates),
                                               settings.llm_model)
                except TimeoutError:
                    choices = []
                    stats["timeouts"] += 1
                latencies.append(time.perf_counter() - started)
                stats["calls"] += 1
                if choices:  # like the API: a failed generation is not cached
                    path.write_text(json.dumps([asdict(c) for c in choices], ensure_ascii=False),
                                    "utf-8")
            if not choices:
                stats["fallbacks"] += 1
            stats["valid_choices"] += len(choices)
            chosen = [candidates[choice.n - 1] for choice in choices]
            llm[case.user_id] = (chosen + [i for i in candidates if i not in chosen])[:10]
            if index % 5 == 0:
                log(f"  LLM: {index}/{len(cases)} (кеш {stats['cache_hits']}, "
                    f"відмов {stats['fallbacks']}, таймаутів {stats['timeouts']})")
    finally:
        await client.aclose()
    summary = {
        "users": len(cases), "model": settings.llm_model, "prompt": PROMPT_VERSION,
        "calls": stats["calls"], "cache_hits": stats["cache_hits"],
        "fallbacks": stats["fallbacks"], "timeouts": stats["timeouts"],
        "mean_valid_choices": stats["valid_choices"] / max(1, len(cases)),
        "mean_latency_s": float(np.mean(latencies)) if latencies else None,
    }
    return llm, base, summary


# ---------------------------------------------------------------- reporting


Row = dict[str, Any]


def metric_rows(
    model: str, segment: str, rankings: dict[int, list[int]], cases: Sequence[EvalCase],
    ks: Sequence[int],
) -> list[Row]:
    if not cases:
        return []
    scores = evaluate_rankings(rankings, {c.user_id: c.relevant for c in cases}, ks)
    return [{"model": model, "segment": segment, "k": k, "metric": metric,
             "value": round(values[k], 6), "users": len(cases)}
            for metric, values in scores.items() for k in ks]


def write_csv(path: Path, rows: list[Row]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["model", "segment", "k", "metric", "value",
                                                    "users"])
        writer.writeheader()
        writer.writerows(rows)


def value_of(rows: list[Row], model: str, segment: str, metric: str, k: int) -> float | None:
    for row in rows:
        if (row["model"], row["segment"], row["metric"], row["k"]) == (model, segment, metric, k):
            return float(row["value"])
    return None


def markdown_table(rows: list[Row], segment: str, ks: Sequence[int]) -> str:
    models = [m for m in MODEL_ORDER if any(r["model"] == m and r["segment"] == segment
                                            for r in rows)]
    header = ["Модель"] + [f"{name}@{k}" for k in ks for name in ("P", "R", "NDCG")]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for model in models:
        cells = [MODEL_LABELS[model]]
        for k in ks:
            for metric in ("precision", "recall", "ndcg"):
                value = value_of(rows, model, segment, metric, k)
                cells.append("—" if value is None else f"{value:.4f}")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def draw_charts(rows: list[Row], domain: Domain, stamp: str, out: Path) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ink, line, paper = "#16161a", "#c9c8c1", "#fafaf7"
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": ink,
        "axes.labelcolor": ink, "xtick.color": ink, "ytick.color": ink,
        "axes.spines.top": False, "axes.spines.right": False,
        "figure.facecolor": paper, "axes.facecolor": paper, "savefig.facecolor": paper,
    })
    title = {"movie": "MovieLens", "book": "Book-Crossing"}[domain]
    files = []

    models = [m for m in MODEL_ORDER if m != "hybrid_llm"
              and value_of(rows, m, "all", "ndcg", 10) is not None]
    labels = [MODEL_LABELS[m] for m in models]
    positions = np.arange(len(models))
    fig, ax = plt.subplots(figsize=(8, 0.6 * len(models) + 1.6))
    all_values = [value_of(rows, m, "all", "ndcg", 10) or 0 for m in models]
    cold_values = [value_of(rows, m, "cold_sim", "ndcg", 10) or 0 for m in models]
    ax.barh(positions - 0.2, all_values, height=0.38, color=ink, label="повна історія")
    ax.barh(positions + 0.2, cold_values, height=0.38, color=paper, edgecolor=ink, hatch="///",
            label=f"холодний старт ({COLD_HISTORY} взаємодій в історії)")
    for y, value in zip(positions - 0.2, all_values, strict=True):
        ax.text(value, y, f" {value:.3f}", va="center", fontsize=8, color=ink)
    ax.set_yticks(positions, labels)
    ax.invert_yaxis()
    ax.set_xlabel("NDCG@10")
    ax.set_title(f"{title}: NDCG@10 на тестовій вибірці", loc="left", fontweight="bold")
    ax.grid(axis="x", color=line, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="lower right", fontsize=8)
    fig.tight_layout()
    name = f"{domain}_{stamp}_ndcg10.png"
    fig.savefig(out / name, dpi=150)
    plt.close(fig)
    files.append(name)

    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6), sharex=True)
    markers = ["o", "s", "^", "D", "v"]
    for ax, metric, label in zip(axes, ("precision", "recall", "ndcg"),
                                 ("Precision@K", "Recall@K", "NDCG@K"), strict=True):
        for model, marker in zip(models, markers, strict=False):
            ax.plot(KS, [value_of(rows, model, "all", metric, k) or 0 for k in KS],
                    marker=marker, color=ink, linewidth=1.2, markersize=4,
                    linestyle="-" if model.startswith("hybrid") else "--",
                    label=MODEL_LABELS[model])
        ax.set_title(label, loc="left", fontweight="bold")
        ax.set_xticks(KS)
        ax.set_xlabel("K")
        ax.grid(color=line, linewidth=0.6)
    axes[0].legend(frameon=False, fontsize=7)
    fig.suptitle(f"{title}: метрики за K", x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    name = f"{domain}_{stamp}_by_k.png"
    fig.savefig(out / name, dpi=150)
    plt.close(fig)
    files.append(name)
    return files


# ---------------------------------------------------------------- main flow


def run(args: argparse.Namespace, domain: Domain) -> dict[str, Any]:
    started = time.perf_counter()
    out: Path = args.output_dir or get_settings().artifacts_dir / "eval"
    out.mkdir(parents=True, exist_ok=True)
    grid = GRIDS[args.grid]

    log(f"=== {domain}: завантаження даних")
    data = load_domain(domain)
    split = split_domain(data)
    log(f"Розбиття {split.stats()}")
    content = NumpyContentRecommender(data.item_ids, data.embeddings)

    als_params, hybrid_params, validation = tune(data, split, grid, args.threads, content)
    log(f"Обрано ALS {asdict(als_params)}, гібрид {hybrid_params}")

    # Final models: train + validation, scored once on test.
    train = split.train + split.validation
    cases = build_cases(train, split.test)
    if args.max_users and len(cases) > args.max_users:
        rng = np.random.default_rng(SEED)
        cases = [cases[i] for i in sorted(rng.choice(len(cases), args.max_users, replace=False))]
    cold = [c for c in cases if c.train_size < COLD_THRESHOLD]
    log(f"Тест: {len(cases)} користувачів, з них холодних {len(cold)}")

    popular_base = PopularityRecommender(data.item_ids, [(r.user_id, r.as_rating()) for r in train])
    als_base = fit_als(train, data.item_ids, als_params)
    models = build_models(popular_base, als_base, content, set(data.item_ids), hybrid_params)
    weighted = models["hybrid_weighted"]
    assert isinstance(weighted, HybridRecommender)
    rows: list[Row] = []
    coverage: dict[str, float] = {}
    for name, model in models.items():
        rankings = rank(model, cases, max(KS), MODEL_LABELS[name])
        rows += metric_rows(name, "all", rankings, cases, KS)
        rows += metric_rows(name, "cold", rankings, cold, KS)
        coverage[name] = catalog_coverage(rankings.values(), len(data.item_ids), 10)
    for name, value in coverage.items():
        rows.append({"model": name, "segment": "all", "k": 10, "metric": "coverage",
                     "value": round(value, 6), "users": len(cases)})

    # Simulated cold start: the same test users, but only COLD_HISTORY training interactions
    # are shown to the models (fresh caches: user IDs repeat with different histories).
    users = {case.user_id for case in cases}
    short = truncate_histories([r for r in train if r.user_id in users], COLD_HISTORY,
                               temporal=split.method == "temporal")
    cold_sim = build_cases(short, split.test, min_train=1)
    log(f"Імітований холодний старт: {len(cold_sim)} користувачів, {COLD_HISTORY} взаємодій")
    sim_models = build_models(popular_base, als_base, content, set(data.item_ids), hybrid_params)
    for name, model in sim_models.items():
        rankings = rank(model, cold_sim, max(KS), f"{MODEL_LABELS[name]} (холодний)")
        rows += metric_rows(name, "cold_sim", rankings, cold_sim, KS)

    llm_summary = None
    if not args.skip_llm and args.llm_users > 0:
        rng = np.random.default_rng(SEED)
        size = min(args.llm_users, len(cases))
        sample = [cases[i] for i in sorted(rng.choice(len(cases), size, replace=False))]
        # Prompt popularity = training interactions only (no leakage from the test split).
        train_counts = dict(Counter(r.item_id for r in train))
        log(f"LLM-переранжування: {len(sample)} користувачів")
        llm, base, llm_summary = asyncio.run(llm_rankings(
            sample, weighted, data, train_counts, out / "llm_cache" / domain,
        ))
        rows += metric_rows("hybrid_weighted", "llm_sample", base, sample, LLM_KS)
        rows += metric_rows("hybrid_llm", "llm_sample", llm, sample, LLM_KS)
        log(f"LLM: {llm_summary}")

    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    csv_name = f"{domain}_{stamp}.csv"
    write_csv(out / csv_name, rows)
    charts = draw_charts(rows, domain, stamp, out)
    params = {
        "domain": domain, "seed": SEED, "selection": f"NDCG@{SELECTION_K} on validation",
        "grid": args.grid, "als": asdict(als_params), "hybrid": hybrid_params,
        "validation": validation,
    }
    (out / f"{domain}_params.json").write_text(
        json.dumps(params, ensure_ascii=False, indent=2), "utf-8")
    summary = {
        "domain": domain, "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "seconds": round(time.perf_counter() - started, 1),
        "split": split.stats(), "relevance_threshold": RELEVANCE_THRESHOLD,
        "catalog_items": len(data.item_ids),
        "test_users": len(cases), "cold_users": len(cold), "cold_threshold": COLD_THRESHOLD,
        "cold_sim_users": len(cold_sim), "cold_history": COLD_HISTORY,
        "max_users": args.max_users or None,
        "params": params, "results": rows, "llm": llm_summary,
        "labels": MODEL_LABELS, "files": {"csv": csv_name, "charts": charts},
    }
    (out / f"{domain}_latest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")

    log(f"Готово за {summary['seconds']} с → {out}")
    print(f"\n### {domain}: усі тестові користувачі ({len(cases)})\n")
    print(markdown_table(rows, "all", KS))
    print(f"\n### {domain}: холодний старт ({len(cold)})\n")
    print(markdown_table(rows, "cold", KS))
    print(f"\n### {domain}: імітований холодний старт ({len(cold_sim)}, "
          f"{COLD_HISTORY} взаємодій)\n")
    print(markdown_table(rows, "cold_sim", KS))
    if llm_summary:
        print(f"\n### {domain}: підвибірка LLM ({llm_summary['users']})\n")
        print(markdown_table(rows, "llm_sample", LLM_KS))
    print("\nПокриття каталогу @10: " + ", ".join(
        f"{MODEL_LABELS[m]} {v:.3f}" for m, v in coverage.items()))
    return summary


def positive_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("має бути невід'ємним")
    return number


def main(argv: Sequence[str] | None = None, runner: Callable[..., Any] = run) -> None:
    parser = argparse.ArgumentParser(description="Наукове оцінювання рекомендаційних моделей")
    parser.add_argument("--domain", choices=("movie", "book", "all"), default="all")
    parser.add_argument("--grid", choices=tuple(GRIDS), default="full")
    parser.add_argument("--llm-users", type=positive_int, default=200)
    parser.add_argument("--skip-llm", action="store_true")
    parser.add_argument("--max-users", type=positive_int, default=0,
                        help="підвибірка тестових користувачів (0 — усі); для швидкої перевірки")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    for domain in ("movie", "book") if args.domain == "all" else (args.domain,):
        runner(args, domain)


if __name__ == "__main__":
    main()
