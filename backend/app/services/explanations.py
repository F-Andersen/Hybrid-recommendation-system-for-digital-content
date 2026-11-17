"""Snapshot, cache and map explanations without holding a transaction during generation."""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, defer

from app.db.models import Interaction, Item, LlmCache, Rating
from app.llm.prompts import PROMPT_VERSION, build_messages
from app.llm.rerank import RerankChoice, clean_explanation
from app.recsys.als import AlsRecommender
from app.recsys.types import Domain
from app.schemas.items import ItemSummary
from app.schemas.recommendations import RecommendationItem, RecommendationSources
from app.services.recommendations import load_history, recommend


@dataclass
class ExplanationSnapshot:
    profile_hash: str
    candidates: list[RecommendationItem]
    messages: list[dict[str, str]]
    cached: list[dict[str, Any]] | None


def cached_result(
    payload: object, candidates: list[RecommendationItem], k: int,
) -> list[RecommendationItem] | None:
    pool = {row.item.id: row for row in candidates[:30]}
    if not isinstance(payload, list) or len(payload) != min(10, len(pool)):
        return None
    if payload and not any(isinstance(row, dict) and row.get("explanation") for row in payload):
        return None
    ordered, seen = [], set()
    for entry in payload:
        if not isinstance(entry, dict):
            return None
        item_id, explanation = entry.get("item_id"), entry.get("explanation")
        if type(item_id) is not int or item_id not in pool or item_id in seen:
            return None
        if explanation is not None and clean_explanation(explanation) != explanation:
            return None
        ordered.append(pool[item_id].model_copy(update={"explanation": explanation}))
        seen.add(item_id)
    ordered.extend(row for row in candidates if row.item.id not in seen)
    return ordered[:k]


def merge_choices(
    candidates: list[RecommendationItem], choices: list[RerankChoice],
) -> list[RecommendationItem]:
    result = [candidates[choice.n - 1].model_copy(update={"explanation": choice.explanation})
              for choice in choices]
    seen = {row.item.id for row in result}
    result.extend(row for row in candidates if row.item.id not in seen)
    return result[:10]


def _summary(item: Item) -> dict[str, Any]:
    return {"title": item.title[:120], "year": item.year,
            "genres": [genre[:40] for genre in item.genres[:4]]}


GENRE_LABELS = {
    "Action": "бойовик", "Adventure": "пригоди", "Animation": "анімація",
    "Children": "дитячий", "Children's": "дитячий", "Comedy": "комедія",
    "Crime": "кримінал", "Documentary": "документальний", "Drama": "драма",
    "Fantasy": "фентезі", "Film-Noir": "нуар", "Horror": "жахи", "IMAX": "IMAX",
    "Musical": "мюзикл", "Mystery": "детектив", "Romance": "мелодрама",
    "Sci-Fi": "наукова фантастика", "Thriller": "трилер", "War": "воєнний",
    "Western": "вестерн", "Fiction": "художня література", "History": "історія",
}


def candidate_evidence(item: Item, high: list[tuple[Rating, Item]]) -> str:
    if item.domain == "book":
        authors = {name.casefold().strip(): name for name in item.creators}
        for _, liked in high:
            shared = sorted(authors.keys() & {name.casefold().strip() for name in liked.creators})
            if shared:
                author = authors[shared[0]]
                if author.isupper():
                    author = author.title()
                return (f"Ви високо оцінили «{liked.title[:60]}». "
                        f"Ім'я автора обох книг — {author[:60]}.")
        for _, liked in high:
            if (item.title.casefold().split(":")[0].strip()
                    == liked.title.casefold().split(":")[0].strip()):
                return f"Назва перегукується з високо оціненою вами «{liked.title[:80]}»."
    overlaps = [(sorted(set(item.genres) & set(liked.genres)), rating, liked)
                for rating, liked in high]
    overlaps.sort(key=lambda value: (-len(value[0]), -value[1].value, value[2].id))
    if overlaps and overlaps[0][0]:
        shared, rating, liked = overlaps[0]
        labels = ", ".join(GENRE_LABELS.get(genre, genre[:40]) for genre in shared[:2])
        return f"Ви оцінили «{liked.title[:60]}» на {rating.value}/10; спільні жанри: {labels}."
    for _, liked in high:
        if (item.title.casefold().split(":")[0].strip()
                == liked.title.casefold().split(":")[0].strip()):
            return f"Назва збігається з високо оціненою вами «{liked.title[:80]}»."
    return "Кандидат має читацькі взаємодії в каталозі; пояснюй лише популярністю." if (
        item.domain == "book" and item.rating_count > 0
    ) else "Кандидат присутній у добірці; запропонуй розглянути його без припущень про смаки."


def prepare_explanation(
    db: Session, user_id: int, domain: Domain, als: AlsRecommender | None,
    model_name: str, *, k: int = 30,
) -> ExplanationSnapshot:
    history = load_history(db, user_id, domain)
    ranked = recommend(db, history, domain, "hybrid", als, max(30, k))
    items = {item.id: item for item in db.scalars(select(Item).options(defer(Item.embedding)).where(
        Item.id.in_([row.item_id for row in ranked]),
    ))}
    candidates = [RecommendationItem(item=ItemSummary.model_validate(items[row.item_id]),
                                     score=row.score, sources=RecommendationSources(
                                         als=row.als, content=row.content, popular=row.popular))
                  for row in ranked if row.item_id in items]
    ratings = db.execute(select(Rating, Item).join(Item).options(defer(Item.embedding)).where(
        Rating.user_id == user_id, Item.domain == domain,
    ).order_by(Rating.item_id)).all()
    views = db.execute(select(Interaction, Item).join(Item).options(defer(Item.embedding)).where(
        Interaction.user_id == user_id, Item.domain == domain,
    ).order_by(Interaction.created_at.desc(), Interaction.id.desc()).limit(10)).all()
    explicit = [(rating, item) for rating, item in ratings if rating.value is not None]
    high = sorted([(rating, item) for rating, item in explicit if rating.value >= 6],
                  key=lambda pair: (-pair[0].value, pair[1].id))[:15]
    low = sorted([(rating, item) for rating, item in explicit if rating.value <= 5],
                 key=lambda pair: (pair[0].value, pair[1].id))[:5]
    genres = Counter(genre for rating, item in ratings
                     if rating.implicit or (rating.value is not None and rating.value >= 6)
                     for genre in item.genres)
    profile = {
        "high_rated": [{**_summary(item), "rating": rating.value} for rating, item in high],
        "low_rated": [{**_summary(item), "rating": rating.value} for rating, item in low],
        "recent_views": [_summary(item) for _, item in views],
        "top_genres": [genre[:60] for genre, _ in sorted(
            genres.items(), key=lambda pair: (-pair[1], pair[0]),
        )[:8]],
    }
    prompt_candidates = [{"n": n, **_summary(items[row.item.id]),
                          "description": (items[row.item.id].description or "")[:200],
                          "evidence": candidate_evidence(items[row.item.id], high),
                          "rating_count": row.item.rating_count}
                         for n, row in enumerate(candidates[:30], start=1)]
    messages = build_messages(profile, prompt_candidates)
    fingerprint = {
        "version": PROMPT_VERSION, "model": model_name, "messages": messages,
        "ratings": [(rating.item_id, rating.value, rating.implicit,
                     rating.rated_at.isoformat() if rating.rated_at else None)
                    for rating, _ in ratings],
        "views": sorted(history.views),
        "recent_views": [(view.id, view.item_id, view.created_at.isoformat()) for view, _ in views],
        "candidates": [row.model_dump(mode="json") for row in candidates[:30]],
    }
    profile_hash = hashlib.sha256(json.dumps(
        fingerprint, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    payload = db.scalar(select(LlmCache.payload).where(
        LlmCache.user_id == user_id, LlmCache.domain == domain,
        LlmCache.profile_hash == profile_hash,
    ))
    return ExplanationSnapshot(profile_hash, candidates, messages, payload)


def save_explanations(
    db: Session, user_id: int, domain: Domain, profile_hash: str,
    result: list[RecommendationItem],
) -> None:
    payload = [{"item_id": row.item.id, "explanation": row.explanation} for row in result]
    statement = insert(LlmCache).values(user_id=user_id, domain=domain,
                                         profile_hash=profile_hash, payload=payload)
    db.execute(statement.on_conflict_do_update(
        index_elements=["user_id", "domain", "profile_hash"],
        set_={"payload": payload, "created_at": func.now()},
    ))
    db.commit()
