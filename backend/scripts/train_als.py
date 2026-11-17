"""Train web-serving ALS artifacts on all current data, separately by domain."""

import argparse
import json
import time
from pathlib import Path

from sqlalchemy import select, text

from app.core.config import get_settings
from app.db.models import Item, Rating
from app.db.session import SessionLocal
from app.recsys.als import AlsParameters, save_model, train_als
from app.recsys.types import Domain, HistoryRating


def train_domain(
    domain: Domain, output: Path, parameters: AlsParameters,
) -> dict[str, int | float | str]:
    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        item_ids = list(session.scalars(select(Item.id).where(
            Item.domain == domain,
        ).order_by(Item.id)))
        rows = session.execute(select(
            Rating.user_id, Rating.item_id, Rating.value, Rating.implicit,
        ).join(Item, Item.id == Rating.item_id).where(Item.domain == domain).order_by(
            Rating.user_id, Rating.item_id,
        )).all()
    user_ids = sorted({row.user_id for row in rows})
    ratings = [(row.user_id, HistoryRating(row.item_id, row.value, row.implicit)) for row in rows]
    print(f"ALS {domain}: {len(user_ids)} користувачів, {len(item_ids)} об'єктів, "
          f"{len(ratings)} взаємодій; навчання…")
    started = time.perf_counter()
    recommender = train_als(user_ids, item_ids, ratings, parameters)
    save_model(recommender, output, domain)
    result = {
        "domain": domain, "users": len(user_ids), "items": len(item_ids),
        "ratings": len(ratings), "positive_interactions": recommender.user_items.nnz,
        "seconds": round(time.perf_counter() - started, 3),
    }
    print("Підсумок ALS: " + json.dumps(result, ensure_ascii=False))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Навчання ALS для вебзастосунку")
    parser.add_argument("--domain", choices=("movie", "book", "all"), default="all")
    parser.add_argument("--factors", type=int, default=64)
    parser.add_argument("--regularization", type=float, default=0.05)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--num-threads", type=int, default=4)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    try:
        parameters = AlsParameters(
            factors=args.factors, regularization=args.regularization,
            iterations=args.iterations, num_threads=args.num_threads,
        )
    except ValueError as exc:
        parser.error(str(exc))
    domains = ("movie", "book") if args.domain == "all" else (args.domain,)
    for domain in domains:
        train_domain(domain, args.output_dir or get_settings().artifacts_dir, parameters)


if __name__ == "__main__":
    main()
