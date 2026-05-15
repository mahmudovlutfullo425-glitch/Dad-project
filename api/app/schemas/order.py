"""Schemas for checkout, order listing, and order detail."""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models import OrderStatus, PaymentStatus


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    variant_id: int
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    amount: Decimal
    currency: str
    status: PaymentStatus


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: OrderStatus
    subtotal: Decimal
    shipping_fee: Decimal
    total: Decimal
    flash_sale_id: int | None = None
    placed_at: datetime
    items: list[OrderItemOut]
    payment: PaymentOut | None = None


class OrderList(BaseModel):
    items: list[OrderOut]
    total: int
    page: int
    page_size: int


class CheckoutRequest(BaseModel):
    address_id: int = Field(gt=0)
    # Payment method is informational for now; Step 10's Celery
    # chain (capture_payment) will branch on it once we add more
    # than the placeholder dev card.
    payment_method: str = Field(default="card", max_length=32)
