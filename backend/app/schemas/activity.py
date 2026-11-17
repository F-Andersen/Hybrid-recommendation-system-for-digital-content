from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.items import ItemSummary


class RatingInput(BaseModel):
    value: int = Field(ge=1, le=10, strict=True)


class RatingResult(BaseModel):
    item_id: int
    value: int
    rated_at: datetime


class RatedItem(BaseModel):
    item: ItemSummary
    value: int
    rated_at: datetime | None


class RatingsPage(BaseModel):
    items: list[RatedItem]
    total: int
    page: int
    page_size: int


class HistoryItem(BaseModel):
    id: int
    item: ItemSummary
    kind: str
    created_at: datetime


class HistoryPage(BaseModel):
    items: list[HistoryItem]
    total: int
    page: int
    page_size: int
