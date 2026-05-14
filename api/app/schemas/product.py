"""Schemas for product and category endpoints."""
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    parent_id: int | None = None


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    variant_name: str
    price: Decimal
    weight_grams: int | None = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    description: str | None = None
    brand: str | None = None
    base_price: Decimal
    is_active: bool
    attributes: dict = Field(default_factory=dict)
    category: CategoryOut
    variants: list[VariantOut]


class ProductList(BaseModel):
    items: list[ProductOut]
    total: int
    page: int
    page_size: int


# --- write models (admin) ---
class VariantIn(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    variant_name: str = Field(min_length=1, max_length=255)
    price: Decimal = Field(ge=0)
    weight_grams: int | None = Field(default=None, ge=0)


class ProductCreate(BaseModel):
    category_id: int
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=280)
    description: str | None = None
    brand: str | None = Field(default=None, max_length=100)
    base_price: Decimal = Field(ge=0)
    attributes: dict = Field(default_factory=dict)
    variants: list[VariantIn] = Field(default_factory=list)


class ProductUpdate(BaseModel):
    category_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=280)
    description: str | None = None
    brand: str | None = Field(default=None, max_length=100)
    base_price: Decimal | None = Field(default=None, ge=0)
    attributes: dict | None = None
    is_active: bool | None = None
