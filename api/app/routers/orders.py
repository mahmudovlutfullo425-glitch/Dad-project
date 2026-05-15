"""Order history and order detail.

The user sees their own orders; admins can see any order. We
return 404 (not 403) for an order that belongs to someone else,
so the endpoint doesn't leak existence to a probing caller.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import Order, User
from app.schemas.order import OrderList, OrderOut

router = APIRouter(tags=["orders"])


def _order_query():
    """Eager-load items and payment in a single round trip."""
    return select(Order).options(
        selectinload(Order.items),
        selectinload(Order.payment),
    )


@router.get(
    "/orders",
    response_model=OrderList,
    summary="List the authenticated user's orders (most recent first)",
)
async def list_orders(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> OrderList:
    count_stmt = select(func.count(Order.id)).where(Order.user_id == user.id)
    total = await db.scalar(count_stmt) or 0

    stmt = (
        _order_query()
        .where(Order.user_id == user.id)
        .order_by(Order.placed_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.scalars(stmt)).all()
    return OrderList(
        items=[OrderOut.model_validate(o) for o in rows],
        total=int(total),
        page=page,
        page_size=page_size,
    )


@router.get(
    "/orders/{order_id}",
    response_model=OrderOut,
    summary="Fetch a single order (own order, or any if admin)",
)
async def get_order(
    order_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderOut:
    order = await db.scalar(_order_query().where(Order.id == order_id))
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if order.user_id != user.id and not user.is_admin:
        # Don't distinguish "doesn't exist" from "isn't yours".
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return OrderOut.model_validate(order)
