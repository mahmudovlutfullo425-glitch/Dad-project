"""Admin-side inventory list — paginated rows joining stock + variant + product.

The customer-facing surface doesn't need a stock list (the search index
carries an `in_stock` boolean and product detail just shows variants);
ops staff need a tabular view to spot variants drifting below their
low-stock threshold. ``low_stock_only=true`` is the most common slice.

Powers the frontend ``/admin/inventory`` page.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_admin
from app.models import InventoryLevel, Product, ProductVariant, User
from app.schemas.admin import InventoryList, InventoryRow

router = APIRouter(prefix="/admin/inventory", tags=["admin"])


@router.get(
    "",
    response_model=InventoryList,
    summary="List inventory levels (admin), optionally filtered to low-stock rows",
)
async def list_inventory(
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    low_stock_only: bool = Query(
        False, description="Only show variants below their low_stock_threshold"
    ),
) -> InventoryList:
    # Join InventoryLevel ↔ ProductVariant ↔ Product so the row carries
    # the human-readable context an operator needs without N+1 lookups.
    base = (
        select(
            InventoryLevel.variant_id,
            ProductVariant.sku,
            Product.id.label("product_id"),
            Product.name.label("product_name"),
            ProductVariant.variant_name,
            InventoryLevel.quantity_on_hand,
            InventoryLevel.quantity_reserved,
            InventoryLevel.low_stock_threshold,
        )
        .join(ProductVariant, ProductVariant.id == InventoryLevel.variant_id)
        .join(Product, Product.id == ProductVariant.product_id)
    )
    count_base = (
        select(func.count(InventoryLevel.variant_id))
        .join(ProductVariant, ProductVariant.id == InventoryLevel.variant_id)
        .join(Product, Product.id == ProductVariant.product_id)
    )

    if low_stock_only:
        cond = InventoryLevel.quantity_on_hand < InventoryLevel.low_stock_threshold
        base = base.where(cond)
        count_base = count_base.where(cond)

    total = await db.scalar(count_base) or 0
    stmt = (
        base.order_by(InventoryLevel.variant_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).mappings().all()
    return InventoryList(
        items=[InventoryRow(**dict(r)) for r in rows],
        total=int(total),
        page=page,
        page_size=page_size,
    )
