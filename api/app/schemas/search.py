"""Schemas for the product search endpoint."""
from pydantic import BaseModel, ConfigDict


class SearchHit(BaseModel):
    """One result row. ``extra='ignore'`` because the Meilisearch
    document carries fields (description, base_price, category_id,
    created_at) the API doesn't surface but we don't want to error
    out over."""

    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    slug: str
    brand: str | None = None
    price: float
    category_name: str
    in_stock: bool


class SearchResponse(BaseModel):
    hits: list[SearchHit]
    total: int
    took_ms: int
    # facets is keyed by attribute name, then value -> count.
    # e.g. {"brand": {"Acme": 12, "Globex": 7}, "category_name": {...}}
    facets: dict[str, dict[str, int]]
