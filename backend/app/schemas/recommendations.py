from pydantic import BaseModel

from app.schemas.items import ItemSummary


class RecommendationSources(BaseModel):
    als: float = 0
    content: float = 0
    popular: float = 0


class RecommendationItem(BaseModel):
    item: ItemSummary
    score: float
    sources: RecommendationSources
    explanation: str | None = None
