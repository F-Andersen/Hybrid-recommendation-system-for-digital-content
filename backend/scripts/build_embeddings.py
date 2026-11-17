"""Resume local BGE-M3 embedding generation; create HNSW after the bulk load."""

import argparse
import asyncio
import json
from collections.abc import Awaitable, Callable

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import Item
from app.db.session import SessionLocal
from app.llm.client import OllamaClient
from app.recsys.content import build_item_text
from app.recsys.types import Domain
from app.recsys.vectors import normalize_vectors

Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]


async def build_embeddings(
    factory: sessionmaker[Session], embed: Embedder,
    *, domain: Domain | None = None, batch_size: int = 32, limit: int | None = None,
) -> dict[str, int]:
    if not 1 <= batch_size <= 32 or (limit is not None and limit < 1):
        raise ValueError("Пакет має містити 1–32 тексти, limit має бути додатним")
    filters = [Item.embedding.is_(None)]
    if domain:
        filters.append(Item.domain == domain)
    with factory() as session:
        pending = session.scalar(select(func.count()).select_from(Item).where(*filters)) or 0
    target = min(pending, limit) if limit else pending
    written = stale = 0
    print(f"Ембединги: потрібно обробити {target} об'єктів")
    while written < target:
        with factory() as session:
            items = session.scalars(select(Item).where(*filters).order_by(Item.id).limit(
                min(batch_size, target - written),
            )).all()
            snapshots = [(item.id, build_item_text(item)) for item in items]
        if not snapshots:
            break
        vectors = normalize_vectors(await embed([value for _, value in snapshots]), len(snapshots))
        with factory.begin() as session:
            for (item_id, source), vector in zip(snapshots, vectors, strict=True):
                item = session.scalar(select(Item).where(Item.id == item_id).with_for_update())
                if item is None or item.embedding is not None:
                    continue
                if build_item_text(item) != source:
                    stale += 1
                    continue
                item.embedding = vector
                written += 1
        print(f"Ембединги: {written}/{target}, змінених під час обробки: {stale}")
    with factory() as session:
        remaining = session.scalar(select(func.count()).select_from(Item).where(
            Item.embedding.is_(None),
        )) or 0
    index_created = 0
    if remaining == 0:
        with factory.begin() as session:
            # Parallel HNSW builds allocate DSM beyond Docker's default 64 MB /dev/shm.
            session.execute(text("SET LOCAL max_parallel_maintenance_workers = 0"))
            session.execute(text("SET LOCAL maintenance_work_mem = '256MB'"))
            index = next(index for index in Item.__table__.indexes
                         if index.name == "ix_items_embedding_hnsw")
            index.create(session.connection(), checkfirst=True)
            session.execute(text("ANALYZE items"))
        index_created = 1
        print("HNSW-індекс готовий")
    return {"written": written, "stale": stale, "remaining": remaining,
            "index_ready": index_created}


async def run(domain: Domain | None, batch_size: int, limit: int | None) -> None:
    settings = get_settings()
    client = OllamaClient(settings.ollama_base_url, timeout=300)
    try:
        async def embed(texts: list[str]) -> list[list[float]]:
            return await client.embed(texts, settings.embed_model)

        result = await build_embeddings(
            SessionLocal, embed, domain=domain, batch_size=batch_size, limit=limit,
        )
        print("Підсумок ембедингів: " + json.dumps(result))
    finally:
        await client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Побудова ембедингів через локальний Ollama")
    parser.add_argument("--domain", choices=("movie", "book"))
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 32 or (args.limit is not None and args.limit < 1):
        parser.error("--batch-size має бути 1–32, --limit має бути додатним")
    asyncio.run(run(args.domain, args.batch_size, args.limit))


if __name__ == "__main__":
    main()
