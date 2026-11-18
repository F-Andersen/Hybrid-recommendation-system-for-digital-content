"""Fill items.cover_url: TMDB posters for films, Open Library ISBN covers for books.

Idempotent: films already checked are marked in meta (`tmdb_poster_checked`), books that
already have a cover are skipped. Secrets are never printed.

Usage:  python -m scripts.fetch_covers [--domain movie|book|all] [--limit N] [--workers 8]
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.integrations.tmdb import TmdbClient, TmdbError

POSTER_SIZE = "w342"
OPENLIBRARY_COVER = "https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg?default=false"
BATCH = 200


def poster_url(client: TmdbClient, base: str, tmdb_id: int) -> str | None:
    try:
        path = client.movie(tmdb_id).get("poster_path")
    except TmdbError as error:
        if "HTTP 404" in str(error):
            return None
        raise
    return f"{base}{POSTER_SIZE}{path}" if isinstance(path, str) and path.startswith("/") else None


def fetch_movies(limit: int | None, workers: int) -> dict[str, int]:
    with SessionLocal() as session:
        rows = session.execute(text(
            "SELECT id, meta->>'tmdbId' AS tmdb FROM items WHERE domain = 'movie' "
            "AND cover_url IS NULL AND meta ? 'tmdbId' "
            "AND NOT coalesce((meta->>'tmdb_poster_checked')::boolean, false) "
            "ORDER BY rating_count DESC, id" + (" LIMIT :limit" if limit else "")),
            {"limit": limit} if limit else {}).all()
    stats = {"pending": len(rows), "found": 0, "missing": 0}
    if not rows:
        return stats
    with httpx.Client(timeout=30, limits=httpx.Limits(max_connections=workers)) as http:
        client = TmdbClient(http, get_settings())
        base = client.configuration()["images"]["secure_base_url"]

        def one(row: Any) -> tuple[int, str | None]:
            return row.id, poster_url(client, base, int(row.tmdb))

        with ThreadPoolExecutor(workers) as pool:
            for start in range(0, len(rows), BATCH):
                results = list(pool.map(one, rows[start:start + BATCH]))
                with SessionLocal() as session:
                    for item_id, url in results:
                        session.execute(text(
                            "UPDATE items SET cover_url = :url, meta = meta || "
                            "'{\"tmdb_poster_checked\": true}'::jsonb WHERE id = :id"),
                            {"url": url, "id": item_id})
                    session.commit()
                found = sum(url is not None for _, url in results)
                stats["found"] += found
                stats["missing"] += len(results) - found
                print(f"фільми: {start + len(results)}/{len(rows)}, постерів {stats['found']}",
                      flush=True)
    return stats


def fill_books() -> dict[str, int]:
    """Point every book without a cover at Open Library; the UI falls back on 404."""
    with SessionLocal() as session:
        updated = session.execute(text(
            "UPDATE items SET cover_url = replace(:template, '{isbn}', external_id) "
            "WHERE domain = 'book' AND cover_url IS NULL AND external_id ~ '^[0-9]{9}[0-9Xx]$'"),
            {"template": OPENLIBRARY_COVER}).rowcount
        session.commit()
    return {"updated": updated}


def main() -> None:
    parser = argparse.ArgumentParser(description="Обкладинки фільмів (TMDB) і книг (Open Library)")
    parser.add_argument("--domain", choices=("movie", "book", "all"), default="all")
    parser.add_argument("--limit", type=int, default=None, help="лише для перевірки")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    summary: dict[str, Any] = {}
    if args.domain in ("movie", "all"):
        summary["movie"] = fetch_movies(args.limit, max(1, min(args.workers, 16)))
    if args.domain in ("book", "all"):
        summary["book"] = fill_books()
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
