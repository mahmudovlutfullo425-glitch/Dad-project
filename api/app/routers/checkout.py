"""POST /checkout — turn a Redis cart into a durable Order.

Pipeline:

1. Read the user's Redis cart.
2. Validate the supplied address belongs to the user.
3. Call ``Inventory.ReserveStock`` over gRPC. The idempotency key is
   a SHA256 of the sorted (variant_id, qty) pairs — a retried POST
   with an unchanged cart returns the same reservation rather than
   double-decrementing stock.
4. Pull variant prices from Postgres, build Order + OrderItems +
   Payment in a single transaction.
5. On any DB failure after a successful reserve, call
   ``ReleaseReservation`` so the stock counters get refunded.
6. Clear the Redis cart.
7. Return ``OrderOut`` (status=pending — Step 10's Celery chain
   will move it to paid/fulfilling).

The Celery enqueue is logged as a TODO for now; without it the
order sits in ``pending`` indefinitely. Step 10 wires the chain.
"""
from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
import grpc
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import inventory_pb2 as pb

from app.db import get_db
from app.deps import get_current_user
from app.grpc_client import get_inventory_stub
from app.models import (
    Address,
    Order,
    OrderItem,
    OrderStatus,
    Payment,
    PaymentStatus,
    ProductVariant,
    User,
)
from app.ratelimit.middleware import rate_limit
from app.redis_client import get_cart_key, get_redis
from app.schemas.order import CheckoutRequest, OrderOut

logger = logging.getLogger(__name__)

router = APIRouter(tags=["checkout"])


def _cart_idempotency_key(user_id: int, cart_qtys: dict[int, int]) -> str:
    """Stable hash of the cart contents — same cart → same key."""
    canonical = json.dumps(sorted(cart_qtys.items()), separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    return f"checkout:{user_id}:{digest}"


@router.post(
    "/checkout",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Place an order from the current Redis cart",
    dependencies=[Depends(rate_limit("CHECKOUT_GLOBAL"))],
)
async def checkout(
    payload: CheckoutRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> OrderOut:
    # --- 1. Read cart from Redis ---
    cart_key = get_cart_key(user.id)
    raw: dict[str, str] = await redis.hgetall(cart_key)
    cart_qtys: dict[int, int] = {}
    for k, v in raw.items():
        try:
            qty = int(v)
            if qty > 0:
                cart_qtys[int(k)] = qty
        except ValueError:
            continue
    if not cart_qtys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cart is empty"
        )

    # --- 2. Validate address ---
    address = await db.get(Address, payload.address_id)
    if address is None or address.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Address not found or not owned by user",
        )

    # --- 3. Reserve stock via gRPC ---
    stub = get_inventory_stub()
    idem_key = _cart_idempotency_key(user.id, cart_qtys)
    items = [
        pb.StockItem(variant_id=vid, quantity=qty) for vid, qty in cart_qtys.items()
    ]
    try:
        reserve_resp = await stub.ReserveStock(
            pb.ReserveStockRequest(
                idempotency_key=idem_key,
                user_id=user.id,
                items=items,
                ttl_seconds=300,
            )
        )
    except grpc.aio.AioRpcError as exc:
        # Translate RESOURCE_EXHAUSTED from inventory's own rate-limit
        # interceptor into a 429 — otherwise it'd surface as a 500.
        if exc.code() == grpc.StatusCode.RESOURCE_EXHAUSTED:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Inventory rate-limited: {exc.details()}",
                headers={"Retry-After": "10"},
            )
        raise
    if not reserve_resp.success:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Insufficient stock: {reserve_resp.error}",
        )
    reservation_id = reserve_resp.reservation_id

    # --- 4. Resolve variant prices ---
    variants = (
        await db.scalars(
            select(ProductVariant).where(ProductVariant.id.in_(cart_qtys.keys()))
        )
    ).all()
    variant_map = {v.id: v for v in variants}
    if len(variant_map) != len(cart_qtys):
        # Cart references a variant that no longer exists.
        await stub.ReleaseReservation(pb.ReleaseRequest(reservation_id=reservation_id))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cart contains unknown variant(s)",
        )

    # --- 5. Build totals + persist order/payment ---
    subtotal = Decimal("0")
    order_items: list[OrderItem] = []
    for vid, qty in cart_qtys.items():
        v = variant_map[vid]
        line_total = v.price * qty
        subtotal += line_total
        order_items.append(
            OrderItem(
                variant_id=vid,
                quantity=qty,
                unit_price=v.price,
                line_total=line_total,
            )
        )
    shipping_fee = Decimal("0")  # free shipping placeholder
    total = subtotal + shipping_fee

    try:
        order = Order(
            user_id=user.id,
            address_id=address.id,
            status=OrderStatus.PENDING,
            subtotal=subtotal,
            shipping_fee=shipping_fee,
            total=total,
            items=order_items,
        )
        db.add(order)
        await db.flush()  # populate order.id for the Payment FK

        payment = Payment(
            order_id=order.id,
            amount=total,
            currency="USD",
            status=PaymentStatus.INITIATED,
        )
        db.add(payment)
        await db.commit()
    except Exception:
        await db.rollback()
        # Refund the Redis stock counters — DB write failed.
        await stub.ReleaseReservation(pb.ReleaseRequest(reservation_id=reservation_id))
        raise

    # --- 6. Clear the cart now that the order is persisted ---
    await redis.delete(cart_key)

    # --- 7. Hand off to the fulfilment pipeline ---
    # TODO Step 10: enqueue tasks.order.process_order.delay(order.id)
    logger.info(
        "checkout: order %s placed (subtotal=%s, items=%d) — awaiting Celery chain",
        order.id,
        subtotal,
        len(order_items),
    )

    # --- 8. Reload with eager-loaded relationships for the response ---
    fresh = await db.scalar(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.payment))
        .where(Order.id == order.id)
    )
    return OrderOut.model_validate(fresh)
