"""Schemas for live-cart endpoints (Redis-backed)."""
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CartItemIn(BaseModel):
    """Body for POST /cart/items — add a variant or increment its quantity."""

    variant_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=999)


class CartItemUpdate(BaseModel):
    """Body for PATCH /cart/items/{variant_id} — set the exact quantity.

    A quantity of 0 deletes the line. The le=999 cap matches the POST
    schema so adds and edits share the same per-line ceiling."""

    quantity: int = Field(ge=0, le=999)


class CartItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    variant_id: int
    sku: str
    name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class CartOut(BaseModel):
    items: list[CartItemOut]
    subtotal: Decimal
    item_count: int
