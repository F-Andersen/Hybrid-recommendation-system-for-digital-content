"""Shared parsing and transactional, repeatable dataset writes."""

import html
import json
import math
import re
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from itertools import islice
from pathlib import Path
from typing import Any, TypeVar

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Item, Rating, User

T = TypeVar("T")


@dataclass
class ImportSummary:
    users: int = 0
    items: int = 0
    ratings: int = 0
    skipped: int = 0
    filtered: int = 0
    duplicates: int = 0

    def print(self) -> None:
        print("Підсумок імпорту: " + json.dumps(asdict(self), ensure_ascii=False))


def batches(rows: Iterable[T], size: int = 1000) -> Iterator[list[T]]:
    iterator = iter(rows)
    while batch := list(islice(iterator, size)):
        yield batch


def clean_text(value: str) -> str:
    return html.unescape(value).replace("\x00", "").strip()


def parse_movie_title(title: str) -> tuple[str, int | None]:
    title = clean_text(title)
    match = re.search(r"\s*\((\d{4})\)\s*$", title)
    return (title[:match.start()].rstrip(), int(match[1])) if match else (title, None)


def normalize_isbn(isbn: str) -> str:
    return re.sub(r"[^0-9X]", "", isbn.upper())


def movie_rating(value: str | float) -> int:
    number = float(value)
    if not math.isfinite(number) or not 0.5 <= number <= 5 or number * 2 != int(number * 2):
        raise ValueError(f"Некоректна оцінка MovieLens: {value}")
    return round(number * 2)


def book_rating(value: str | int) -> tuple[int | None, bool]:
    number = int(value)
    if not 0 <= number <= 10:
        raise ValueError(f"Некоректна оцінка Book-Crossing: {value}")
    return (None, True) if number == 0 else (number, False)


def read_bx(path: Path, summary: ImportSummary) -> pd.DataFrame:
    def skip_bad_line(fields: list[str]) -> None:
        summary.skipped += 1
        return None

    # Callable equivalent of on_bad_lines='skip', also counts malformed records.
    frame = pd.read_csv(
        path, sep=";", encoding="latin-1", dtype=str, keep_default_na=False,
        engine="python", on_bad_lines=skip_bad_line,
    )
    frame = frame.fillna("")
    frame.columns = [column.lstrip("\ufeff").strip() for column in frame.columns]
    return frame


def upsert_users(session: Session, source: str, external_ids: Iterable[str]) -> dict[str, int]:
    for batch in batches(sorted(set(external_ids))):
        statement = insert(User).values([
            {"source": source, "external_id": value, "display_name": f"{source} {value}"}
            for value in batch
        ])
        session.execute(statement.on_conflict_do_nothing(index_elements=["source", "external_id"]))
    return dict(session.execute(
        select(User.external_id, User.id).where(User.source == source)
    ).all())


def upsert_items(session: Session, source: str, rows: list[dict[str, Any]]) -> dict[str, int]:
    for batch in batches(rows):
        statement = insert(Item).values(batch)
        fields = [key for key in batch[0] if key not in {"source", "external_id", "domain"}]
        updates = {key: getattr(statement.excluded, key) for key in fields}
        # Preserve Open Library metadata across a repeated Book-Crossing import.
        updates["meta"] = Item.meta.op("||")(statement.excluded.meta)
        session.execute(statement.on_conflict_do_update(
            index_elements=["source", "external_id"], set_=updates,
        ))
    return dict(session.execute(
        select(Item.external_id, Item.id).where(Item.source == source)
    ).all())


def upsert_ratings(session: Session, rows: Iterable[dict[str, Any]]) -> None:
    for batch in batches(rows):
        statement = insert(Rating).values(batch)
        session.execute(statement.on_conflict_do_update(
            index_elements=["user_id", "item_id"],
            set_={key: getattr(statement.excluded, key)
                  for key in ("value", "implicit", "rated_at")},
        ))


def refresh_rating_stats(session: Session, source: str) -> None:
    # Count all interactions, but average only explicit values (AVG ignores NULL).
    session.execute(text("""
        UPDATE items AS i SET rating_count = s.n, rating_avg = COALESCE(s.avg, 0)
        FROM (
            SELECT i2.id, count(r.item_id)::integer AS n, avg(r.value) AS avg
            FROM items i2 LEFT JOIN ratings r ON r.item_id = i2.id
            WHERE i2.source = :source GROUP BY i2.id
        ) s WHERE i.id = s.id
    """), {"source": source})
