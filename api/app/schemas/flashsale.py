"""Schemas for flash-sale browsing and the fast-buy path."""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models import FlashSaleStatus


class FlashSaleItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    variant_id: int
    sale_price: Decimal
    quantity_allocated: int
    per_user_limit: int


class FlashSaleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    starts_at: datetime
    ends_at: datetime
    status: FlashSaleStatus
    items: list[FlashSaleItemOut] = []


class FlashSaleBuyRequest(BaseModel):
    variant_id: int = Field(gt=0)
    # le=10 is a hard ceiling — actual cap comes from per_user_limit on
    # the FlashSaleItem and is checked server-side.
    quantity: int = Field(ge=1, le=10)
