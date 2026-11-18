"""Import MovieLens CSV or 1M DAT files without duplicating records."""

import argparse
import csv
from collections import Counter, defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Item
from app.db.session import SessionLocal
from scripts.data_common import (
    ImportSummary,
    batches,
    clean_text,
    movie_rating,
    parse_movie_title,
    refresh_rating_stats,
    upsert_items,
    upsert_ratings,
    upsert_users,
)

VARIANTS = ("ml-latest-small", "ml-1m", "ml-25m")
CSV_VARIANTS = ("ml-latest-small", "ml-25m")
LARGE_VARIANTS = ("ml-25m",)


def read_records(path: Path, columns: list[str] | None = None) -> Iterator[dict[str, str]]:
    with path.open(encoding="latin-1" if columns else "utf-8-sig", newline="") as stream:
        if columns:
            for line in stream:
                fields = line.rstrip("\r\n").split("::")
                if len(fields) != len(columns):
                    raise ValueError(f"Пошкоджений рядок у {path.name}: {line[:100]}")
                yield dict(zip(columns, fields, strict=True))
        else:
            yield from csv.DictReader(stream)


def load_movies(directory: Path, variant: str, summary: ImportSummary) -> list[dict[str, Any]]:
    tags: dict[str, Counter[str]] = defaultdict(Counter)
    links: dict[str, dict[str, str]] = {}
    if variant in CSV_VARIANTS:
        for row in read_records(directory / "tags.csv"):
            tag = clean_text(row["tag"])
            if tag:
                tags[row["movieId"]][tag] += 1
        for row in read_records(directory / "links.csv"):
            links[row["movieId"]] = {
                key: row[key] for key in ("imdbId", "tmdbId") if row[key]
            }
        records = read_records(directory / "movies.csv")
    else:
        records = read_records(directory / "movies.dat", ["movieId", "title", "genres"])
    movies: dict[str, dict[str, Any]] = {}
    for row in records:
        external_id = row["movieId"].strip()
        title, year = parse_movie_title(row["title"])
        if not external_id.isdigit() or not title:
            summary.skipped += 1
            continue
        if external_id in movies:
            summary.duplicates += 1
        movies[external_id] = {
            "source": "movielens", "domain": "movie", "external_id": external_id,
            "title": title, "year": year, "creators": [],
            "genres": [g for g in row["genres"].split("|") if g and g != "(no genres listed)"],
            "meta": {"tags": [tag for tag, _ in sorted(
                tags[external_id].items(), key=lambda pair: (-pair[1], pair[0]),
            )[:15]], "dataset_variant": variant, **links.get(external_id, {})},
        }
    return list(movies.values())


def load_large_ratings(
    directory: Path, movie_ids: set[str], max_users: int | None, min_movie_ratings: int,
    seed: int, summary: ImportSummary,
) -> tuple[pd.DataFrame, set[str]]:
    """Vectorised path for 25M ratings: the catalogue is filtered on the full data,
    ratings are kept for a seeded user sample so experiments fit in memory."""
    frame = pd.read_csv(directory / "ratings.csv", dtype={
        "userId": "int32", "movieId": "int32", "rating": "float32", "timestamp": "int64",
    })
    valid = (frame["rating"] >= 0.5) & (frame["rating"] <= 5) & (
        (frame["rating"] * 2) % 1 == 0) & frame["movieId"].astype(str).isin(movie_ids)
    summary.skipped += int((~valid).sum())
    frame = frame[valid]
    duplicated = frame.duplicated(["userId", "movieId"], keep=False)
    summary.duplicates += int(duplicated.sum())
    frame = frame.sort_values("timestamp").drop_duplicates(["userId", "movieId"], keep="last")
    counts = frame["movieId"].value_counts()
    kept = {str(movie) for movie in counts[counts >= min_movie_ratings].index}
    summary.filtered += int((~frame["movieId"].astype(str).isin(kept)).sum())
    frame = frame[frame["movieId"].astype(str).isin(kept)]
    users = np.sort(frame["userId"].unique())
    if max_users and len(users) > max_users:
        sample = np.random.default_rng(seed).choice(users, max_users, replace=False)
        before = len(frame)
        frame = frame[frame["userId"].isin(sample)]
        summary.filtered += before - len(frame)
    return frame, kept


def purge_movielens(session: Session, keep_movies: set[str]) -> None:
    """Replace a previous MovieLens variant: user IDs are not shared between variants.
    Films with the same movieId keep their rows (embeddings, posters)."""
    session.execute(text("DELETE FROM llm_cache WHERE domain = 'movie'"))
    session.execute(text(
        "DELETE FROM ratings r USING users u WHERE r.user_id = u.id AND u.source = 'movielens'"))
    session.execute(text(
        "DELETE FROM interactions i USING users u "
        "WHERE i.user_id = u.id AND u.source = 'movielens'"))
    session.execute(text("DELETE FROM users WHERE source = 'movielens'"))
    stale = [item_id for item_id, external_id in session.execute(select(Item.id, Item.external_id)
             .where(Item.source == "movielens")) if external_id not in keep_movies]
    for batch in batches(stale, 5000):
        session.execute(text("DELETE FROM interactions WHERE item_id = ANY(:ids)"), {"ids": batch})
        session.execute(text("DELETE FROM ratings WHERE item_id = ANY(:ids)"), {"ids": batch})
        session.execute(text("DELETE FROM items WHERE id = ANY(:ids)"), {"ids": batch})


def import_dataset(
    session: Session, directory: Path, variant: str, *, replace: bool = False,
    max_users: int | None = None, min_movie_ratings: int = 0, seed: int = 42,
) -> ImportSummary:
    existing = set(session.scalars(select(Item.meta["dataset_variant"].astext).where(
        Item.source == "movielens",
    )))
    if existing and existing != {variant} and not replace:
        raise ValueError(
            "Не можна змішувати варіанти MovieLens: ID користувачів між ними не узгоджені. "
            "Додайте --replace, щоб замінити попередній варіант."
        )
    summary = ImportSummary()
    movies = load_movies(directory, variant, summary)
    if variant in LARGE_VARIANTS:
        return import_large(session, directory, variant, movies, summary, replace=replace,
                            max_users=max_users, min_movie_ratings=min_movie_ratings, seed=seed)
    if replace:
        purge_movielens(session, {row["external_id"] for row in movies})
    movie_ids = {row["external_id"] for row in movies}
    records = (
        read_records(directory / "ratings.csv") if variant in CSV_VARIANTS else
        read_records(directory / "ratings.dat", ["userId", "movieId", "rating", "timestamp"])
    )
    ratings: dict[tuple[str, str], dict[str, Any]] = {}
    for row in records:
        try:
            user, movie = row["userId"].strip(), row["movieId"].strip()
            if not user.isdigit() or movie not in movie_ids:
                raise ValueError("Невідомий користувач або фільм")
            rating = {
                "value": movie_rating(row["rating"]), "implicit": False,
                "rated_at": datetime.fromtimestamp(int(row["timestamp"]), tz=UTC),
            }
        except (ValueError, OverflowError, OSError, TypeError, KeyError):
            summary.skipped += 1
            continue
        key = (user, movie)
        if key in ratings:
            summary.duplicates += 1
        if key not in ratings or rating["rated_at"] >= ratings[key]["rated_at"]:
            ratings[key] = rating
    if not movies or not ratings:
        raise ValueError("MovieLens не містить придатних фільмів або оцінок")
    users = upsert_users(session, "movielens", (user for user, _ in ratings))
    items = upsert_items(session, "movielens", movies)
    upsert_ratings(session, (
        {"user_id": users[user], "item_id": items[movie], **rating}
        for (user, movie), rating in ratings.items()
    ))
    refresh_rating_stats(session, "movielens")
    summary.users = len({user for user, _ in ratings})
    summary.items, summary.ratings = len(movies), len(ratings)
    return summary


def import_large(
    session: Session, directory: Path, variant: str, movies: list[dict[str, Any]],
    summary: ImportSummary, *, replace: bool, max_users: int | None, min_movie_ratings: int,
    seed: int,
) -> ImportSummary:
    frame, kept = load_large_ratings(directory, {row["external_id"] for row in movies},
                                     max_users, min_movie_ratings, seed, summary)
    movies = [row for row in movies if row["external_id"] in kept]
    if not movies or frame.empty:
        raise ValueError("MovieLens не містить придатних фільмів або оцінок")
    for row in movies:
        row["meta"] = {**row["meta"], "min_ratings": min_movie_ratings,
                       "user_sample": max_users or None}
    if replace:
        purge_movielens(session, kept)
    user_ids = [str(user) for user in frame["userId"].unique()]
    users = upsert_users(session, "movielens", user_ids)
    items = upsert_items(session, "movielens", movies)
    values = (frame["rating"].to_numpy() * 2).round().astype(int)
    stamps = pd.to_datetime(frame["timestamp"].to_numpy(), unit="s", utc=True)
    upsert_ratings(session, (
        {"user_id": users[str(user)], "item_id": items[str(movie)], "value": int(value),
         "implicit": False, "rated_at": stamp.to_pydatetime()}
        for user, movie, value, stamp in zip(
            frame["userId"].to_numpy(), frame["movieId"].to_numpy(), values, stamps,
            strict=True)
    ))
    refresh_rating_stats(session, "movielens")
    summary.users, summary.items, summary.ratings = len(user_ids), len(movies), len(frame)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Імпорт MovieLens")
    parser.add_argument("--variant", choices=VARIANTS, default="ml-25m")
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--replace", action="store_true",
                        help="замінити попередній варіант MovieLens (користувачі й оцінки)")
    parser.add_argument("--max-users", type=int, default=25_000,
                        help="ml-25m: випадкова вибірка користувачів (seed 42); 0 — усі")
    parser.add_argument("--min-movie-ratings", type=int, default=20,
                        help="ml-25m: мінімум оцінок фільму в повному наборі")
    args = parser.parse_args()
    directory = args.input_dir or get_settings().data_dir / args.variant
    with SessionLocal.begin() as session:
        summary = import_dataset(session, directory, args.variant, replace=args.replace,
                                 max_users=args.max_users or None,
                                 min_movie_ratings=args.min_movie_ratings)
    summary.print()


if __name__ == "__main__":
    main()
