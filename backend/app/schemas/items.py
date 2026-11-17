from typing import Any

from pydantic import BaseModel, ConfigDict

from app.recsys.types import Domain


class ItemSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain: Domain
    title: str
    year: int | None
    creators: list[str]
    genres: list[str]
    cover_url: str | None
    rating_count: int
    rating_avg: float


class ItemDetail(ItemSummary):
    description: str | None
    meta: dict[str, Any]
    my_rating: int | None = None


class ItemPage(BaseModel):
    items: list[ItemSummary]
    total: int
    page: int
    page_size: int


class SimilarItem(BaseModel):
    item: ItemSummary
    score: float


class GenreCount(BaseModel):
    genre: str
    count: int
