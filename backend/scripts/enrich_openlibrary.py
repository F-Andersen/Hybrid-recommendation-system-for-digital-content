"""Resume cached Open Library enrichment of imported (k-core) books."""

import argparse
import json
import time
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import Item
from app.db.session import SessionLocal
from scripts.data_common import batches, clean_text

USER_AGENT = (
    "HybridRecommender/0.1 "
    "(https://github.com/F-Andersen/Hybrid-recommendation-system-for-digital-content)"
)


class OpenLibraryClient:
    def __init__(self, client: httpx.Client, cache_dir: Path, delay: float = 1.0) -> None:
        self.client = client
        self.cache_dir = cache_dir
        self.delay = max(1.0, delay)
        self.last_request = 0.0
        self.requests = 0
        self.cache_hits = 0
        cache_dir.mkdir(parents=True, exist_ok=True)

    def get_books(self, isbns: list[str]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        missing = []
        for isbn in isbns:
            path = self.cache_dir / f"{isbn}.json"
            if path.exists():
                try:
                    cached = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(cached, dict):
                        result[isbn] = cached
                        self.cache_hits += 1
                        continue
                except (ValueError, OSError):
                    pass
            missing.append(isbn)
        for batch in batches(missing, 50):
            payload = self._request(batch)
            for isbn in batch:
                # Cache absent ISBNs too, so subsequent runs do not query them again.
                result[isbn] = payload.get(f"ISBN:{isbn}", {})
                path = self.cache_dir / f"{isbn}.json"
                partial = path.with_suffix(".json.part")
                partial.write_text(json.dumps(result[isbn], ensure_ascii=False), encoding="utf-8")
                partial.replace(path)
        return result

    def _request(self, isbns: list[str]) -> dict[str, Any]:
        for attempt in range(4):
            time.sleep(max(0.0, self.delay - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            self.requests += 1
            try:
                response = self.client.get("https://openlibrary.org/api/books", params={
                    "bibkeys": ",".join(f"ISBN:{isbn}" for isbn in isbns),
                    "format": "json", "jscmd": "details",
                })
                if (response.status_code == 429 or response.status_code >= 500) and attempt < 3:
                    retry_after = response.headers.get("Retry-After", "")
                    pause = float(retry_after) if retry_after.isdigit() else 2 ** (attempt + 1)
                    time.sleep(max(self.delay, pause))
                    continue
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or any(
                    not isinstance(value, dict) for value in payload.values()
                ):
                    raise ValueError("Некоректна структура відповіді Open Library")
                return payload
            except (httpx.TransportError, ValueError):
                if attempt == 3:
                    raise
                time.sleep(2 ** (attempt + 1))
        raise RuntimeError("Open Library не відповідає")


def extract_metadata(record: dict[str, Any]) -> tuple[str | None, list[str]]:
    details = record.get("details", {})
    if not isinstance(details, dict):
        return None, []
    description = details.get("description")
    if isinstance(description, dict):
        description = description.get("value")
    description = clean_text(description) if isinstance(description, str) else None
    subjects = details.get("subjects", [])
    genres = []
    if isinstance(subjects, list):
        for subject in subjects:
            name = subject.get("name") if isinstance(subject, dict) else subject
            if isinstance(name, str) and clean_text(name):
                genres.append(clean_text(name))
    return description or None, list(dict.fromkeys(genres))


def enrich(
    factory: sessionmaker[Session], client: OpenLibraryClient, limit: int | None = None,
) -> dict[str, int]:
    with factory() as session:
        query = select(Item.id, Item.external_id).where(
            Item.domain == "book", Item.source == "bookcrossing",
        ).order_by(Item.id)
        if limit is not None:
            query = query.limit(limit)
        rows = session.execute(query).all()
    updated = descriptions = missing = 0
    for batch in batches(rows, 50):
        payload = client.get_books([row.external_id for row in batch])
        with factory.begin() as session:
            for row in batch:
                item = session.get(Item, row.id)
                if item is None:
                    continue
                record = payload[row.external_id]
                description, genres = extract_metadata(record)
                if not record:
                    missing += 1
                if description:
                    item.description = description
                    descriptions += 1
                if genres:
                    item.genres = genres
                item.cover_url = (
                    f"https://covers.openlibrary.org/b/isbn/{row.external_id}-M.jpg?default=false"
                )
                if record:
                    item.meta = {**item.meta, "openlibrary": {"info_url": record.get("info_url")}}
                updated += 1
        print(f"Open Library: {updated}/{len(rows)}, анотацій: {descriptions}")
    return {
        "books": updated, "descriptions": descriptions, "not_found": missing,
        "requests": client.requests, "cache_hits": client.cache_hits,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Збагачення книг через Open Library")
    parser.add_argument("--limit", type=int, help="Обробити перші N книг для перевірки")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit має бути додатним")
    with httpx.Client(
        timeout=45, follow_redirects=True, headers={"User-Agent": USER_AGENT},
    ) as http:
        client = OpenLibraryClient(http, get_settings().data_dir / "openlibrary_cache")
        result = enrich(SessionLocal, client, args.limit)
    print("Підсумок збагачення: " + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
