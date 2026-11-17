"""Import MovieLens CSV or 1M DAT files without duplicating records."""

import argparse
import csv
from collections import Counter, defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Item
from app.db.session import SessionLocal
from scripts.data_common import (
    ImportSummary,
    clean_text,
    movie_rating,
    parse_movie_title,
    refresh_rating_stats,
    upsert_items,
    upsert_ratings,
    upsert_users,
)

VARIANTS = ("ml-latest-small", "ml-1m")


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
    if variant == "ml-latest-small":
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


def import_dataset(session: Session, directory: Path, variant: str) -> ImportSummary:
    existing = set(session.scalars(select(Item.meta["dataset_variant"].astext).where(
        Item.source == "movielens",
    )))
    if existing and existing != {variant}:
        raise ValueError(
            "Не можна змішувати варіанти MovieLens: ID користувачів між ними не узгоджені. "
            "Використайте окрему базу для іншого варіанта."
        )
    summary = ImportSummary()
    movies = load_movies(directory, variant, summary)
    movie_ids = {row["external_id"] for row in movies}
    records = (
        read_records(directory / "ratings.csv") if variant == "ml-latest-small" else
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Імпорт MovieLens")
    parser.add_argument("--variant", choices=VARIANTS, default="ml-latest-small")
    parser.add_argument("--input-dir", type=Path)
    args = parser.parse_args()
    directory = args.input_dir or get_settings().data_dir / args.variant
    with SessionLocal.begin() as session:
        summary = import_dataset(session, directory, args.variant)
    summary.print()


if __name__ == "__main__":
    main()
