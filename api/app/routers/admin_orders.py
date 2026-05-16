"""Admin-side orders list — unscoped, paginated, status-filterable.

Unlike :mod:`app.routers.orders` (which filters by ``user_id`` so a
customer only sees their own), this endpoint returns every order
in the system and is gated by :func:`app.deps.get_current_admin`.

Powers the frontend ``/admin/orders`` page.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_admin
from app.models import Order, OrderStatus, User
from app.schemas.order import OrderList, OrderOut

router = APIRouter(prefix="/admin/orders", tags=["admin"])


@router.get(
    "",
    response_model=OrderList,
    summary="List all orders (admin), optionally filtered by status",
)
async def list_all_orders(
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: OrderStatus | None = Query(None, description="Filter by order status"),
) -> OrderList:
    count_stmt = select(func.count(Order.id))
    list_stmt = select(Order).options(
        selectinload(Order.items),
        selectinload(Order.payment),
    )

    if status is not None:
        count_stmt = count_stmt.where(Order.status == status)
        list_stmt = list_stmt.where(Order.status == status)

    total = await db.scalar(count_stmt) or 0
    list_stmt = (
        list_stmt.order_by(Order.placed_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.scalars(list_stmt)).all()
    return OrderList(
        items=[OrderOut.model_validate(o) for o in rows],
        total=int(total),
        page=page,
        page_size=page_size,
    )
