"""Schemas for admin-only endpoints not covered by reused customer schemas."""
from pydantic import BaseModel


class InventoryRow(BaseModel):
    """Inventory ops view: stock-level row joined with variant context."""

    variant_id: int
    sku: str
    product_id: int
    product_name: str
    variant_name: str
    quantity_on_hand: int
    quantity_reserved: int
    low_stock_threshold: int


class InventoryList(BaseModel):
    items: list[InventoryRow]
    total: int
    page: int
    page_size: int
