"""Import the stable Book-Crossing k-core, preserving implicit feedback."""

import argparse
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from scripts.data_common import (
    ImportSummary,
    book_rating,
    clean_text,
    normalize_isbn,
    read_bx,
    refresh_rating_stats,
    upsert_items,
    upsert_ratings,
    upsert_users,
)


def filter_k_core(
    ratings: pd.DataFrame, min_user: int = 5, min_book: int = 10,
) -> pd.DataFrame:
    if min_user < 1 or min_book < 1:
        raise ValueError("Пороги k-core мають бути додатними")
    while not ratings.empty:
        before = len(ratings)
        ratings = ratings[ratings.groupby("ISBN")["ISBN"].transform("size") >= min_book]
        ratings = ratings[ratings.groupby("User-ID")["User-ID"].transform("size") >= min_user]
        if len(ratings) == before:
            break
    return ratings


def parse_year(value: str) -> int | None:
    try:
        year = int(value)
    except ValueError:
        return None
    return year if 1 <= year <= 2100 else None


def import_dataset(
    session: Session, directory: Path, min_user: int = 5, min_book: int = 10,
) -> ImportSummary:
    summary = ImportSummary()
    books = read_bx(directory / "BX-Books.csv", summary)
    users = read_bx(directory / "BX-Users.csv", summary)
    ratings = read_bx(directory / "BX-Book-Ratings.csv", summary)
    books["ISBN"] = books["ISBN"].map(normalize_isbn)
    valid_books = books["ISBN"].str.len().isin([10, 13]) & books["Book-Title"].str.strip().ne("")
    summary.skipped += int((~valid_books).sum())
    books = books[valid_books]
    summary.duplicates += int(books.duplicated("ISBN").sum())
    books = books.drop_duplicates("ISBN", keep="first")
    users["User-ID"] = users["User-ID"].str.strip()
    valid_users = users["User-ID"].str.fullmatch(r"\d+")
    summary.skipped += int((~valid_users).sum())
    users = users[valid_users]
    ratings["ISBN"] = ratings["ISBN"].map(normalize_isbn)
    ratings["User-ID"] = ratings["User-ID"].str.strip()
    numeric = pd.to_numeric(ratings["Book-Rating"], errors="coerce")
    valid_ratings = (
        numeric.between(0, 10) & numeric.eq(numeric.round())
        & ratings["ISBN"].isin(books["ISBN"]) & ratings["User-ID"].isin(users["User-ID"])
    )
    summary.skipped += int((~valid_ratings).sum())
    ratings = ratings[valid_ratings].copy()
    ratings["Book-Rating"] = numeric[valid_ratings].astype(int)
    summary.duplicates += int(ratings.duplicated(["User-ID", "ISBN"]).sum())
    ratings = ratings.drop_duplicates(["User-ID", "ISBN"], keep="last")
    before = len(ratings)
    ratings = filter_k_core(ratings, min_user, min_book)
    summary.filtered = before - len(ratings)
    if ratings.empty:
        raise ValueError("Після фільтрації k-core не залишилося взаємодій")
    books = books[books["ISBN"].isin(ratings["ISBN"])]
    item_rows: list[dict[str, Any]] = []
    for row in books.to_dict("records"):
        author = clean_text(row["Book-Author"])
        item_rows.append({
            "source": "bookcrossing", "domain": "book", "external_id": row["ISBN"],
            "title": clean_text(row["Book-Title"]), "year": parse_year(row["Year-Of-Publication"]),
            "creators": [author] if author else [],
            "meta": {"publisher": clean_text(row["Publisher"])},
        })
    user_ids = upsert_users(session, "bookcrossing", ratings["User-ID"])
    item_ids = upsert_items(session, "bookcrossing", item_rows)

    def rating_rows() -> Iterator[dict[str, Any]]:
        for user, isbn, value in ratings[["User-ID", "ISBN", "Book-Rating"]].itertuples(
            index=False, name=None,
        ):
            score, implicit = book_rating(value)
            yield {
                "user_id": user_ids[user], "item_id": item_ids[isbn],
                "value": score, "implicit": implicit, "rated_at": None,
            }

    upsert_ratings(session, rating_rows())
    refresh_rating_stats(session, "bookcrossing")
    summary.users = int(ratings["User-ID"].nunique())
    summary.items, summary.ratings = len(books), len(ratings)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Імпорт Book-Crossing")
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--min-user", type=int, default=5)
    parser.add_argument("--min-book", type=int, default=5)
    args = parser.parse_args()
    with SessionLocal.begin() as session:
        summary = import_dataset(
            session, args.input_dir or get_settings().data_dir / "bookcrossing",
            args.min_user, args.min_book,
        )
    summary.print()


if __name__ == "__main__":
    main()
