"""Flash sales — browse, detail, fast-buy.

The buy path bypasses the cart on purpose: a flash-sale shopper wants
the lowest possible latency between "click" and "order placed". The
request goes:

    rate-limit → time-window check → per-user-limit check
      → ReserveStock (gRPC) → Order + Payment (Postgres) → response

Per-user purchase tracking lives in Redis as ``fs_purchased:{fsid}:{uid}``.
``INCRBY quantity`` atomically computes the new total; if it overshoots
the configured ``per_user_limit`` we ``DECRBY`` it back and reject.

ClickHouse event emission is a Step-11 wire-up; for now we log the
attempt result so the verification path is still observable.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
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
    FlashSale,
    FlashSaleStatus,
    Order,
    OrderItem,
    OrderStatus,
    Payment,
    PaymentStatus,
    User,
)
from app.ratelimit.middleware import rate_limit
from app.redis_client import get_redis
from app.schemas.flashsale import FlashSaleBuyRequest, FlashSaleOut
from app.schemas.order import OrderOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/flashsales", tags=["flashsales"])


def _purchased_key(flash_sale_id: int, user_id: int) -> str:
    return f"fs_purchased:{flash_sale_id}:{user_id}"


def _is_buyable_now(fs: FlashSale) -> bool:
    """Time-window check.

    Status is informational; the gate is whether *now* falls inside
    [starts_at, ends_at] AND the sale wasn't explicitly ended or
    cancelled. This lets a SCHEDULED sale go live without an
    explicit activator (Step 10's beat job will sweep statuses)."""
    if fs.status in (FlashSaleStatus.ENDED, FlashSaleStatus.CANCELLED):
        return False
    now = datetime.now(timezone.utc)
    return fs.starts_at <= now <= fs.ends_at


@router.get(
    "",
    response_model=list[FlashSaleOut],
    summary="List flash sales that haven't ended yet",
)
async def list_flashsales(db: AsyncSession = Depends(get_db)) -> list[FlashSaleOut]:
    now = datetime.now(timezone.utc)
    stmt = (
        select(FlashSale)
        .options(selectinload(FlashSale.items))
        .where(FlashSale.ends_at >= now)
        .where(FlashSale.status != FlashSaleStatus.CANCELLED)
        .order_by(FlashSale.starts_at)
    )
    return [FlashSaleOut.model_validate(f) for f in (await db.scalars(stmt)).all()]


@router.get(
    "/{flash_sale_id}",
    response_model=FlashSaleOut,
    summary="Flash sale detail with items",
)
async def get_flashsale(
    flash_sale_id: int, db: AsyncSession = Depends(get_db)
) -> FlashSaleOut:
    fs = await db.scalar(
        select(FlashSale)
        .options(selectinload(FlashSale.items))
        .where(FlashSale.id == flash_sale_id)
    )
    if fs is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Flash sale not found"
        )
    return FlashSaleOut.model_validate(fs)


@router.post(
    "/{flash_sale_id}/buy",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Fast-path purchase from a flash sale (rate-limited per user)",
    dependencies=[Depends(rate_limit("FLASH_BUY_PER_USER"))],
)
async def buy_flashsale(
    flash_sale_id: int,
    payload: FlashSaleBuyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> OrderOut:
    # --- 1. Validate flash sale and its current window ---
    fs = await db.scalar(
        select(FlashSale)
        .options(selectinload(FlashSale.items))
        .where(FlashSale.id == flash_sale_id)
    )
    if fs is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Flash sale not found"
        )
    if not _is_buyable_now(fs):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Flash sale is not currently active",
        )

    fs_item = next(
        (it for it in fs.items if it.variant_id == payload.variant_id), None
    )
    if fs_item is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Variant is not part of this flash sale",
        )

    # --- 2. Quantity vs the rule's hard cap (per-item, before INCR) ---
    if payload.quantity > fs_item.per_user_limit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Quantity exceeds per-user limit ({fs_item.per_user_limit})",
        )

    # --- 3. Per-user purchase counter ---
    counter_key = _purchased_key(fs.id, user.id)
    new_total = await redis.incrby(counter_key, payload.quantity)
    # Keep the counter around for the lifetime of the sale plus a
    # small grace period for late writes; then let it expire.
    ttl_seconds = max(
        60, int((fs.ends_at - datetime.now(timezone.utc)).total_seconds()) + 60
    )
    await redis.expire(counter_key, ttl_seconds)

    if new_total > fs_item.per_user_limit:
        await redis.decrby(counter_key, payload.quantity)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Per-user limit reached ({fs_item.per_user_limit}); "
                f"you already have {new_total - payload.quantity} in this sale"
            ),
        )

    # --- 4. Pick an address (default, falling back to first) ---
    address = await db.scalar(
        select(Address)
        .where(Address.user_id == user.id)
        .order_by(Address.is_default.desc(), Address.id)
        .limit(1)
    )
    if address is None:
        await redis.decrby(counter_key, payload.quantity)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no address on file",
        )

    # --- 5. Reserve stock via gRPC ---
    stub = get_inventory_stub()
    # Idempotency key embeds the cumulative purchased count so a retry
    # of the same buy returns the same reservation, but a *new* buy
    # (after the previous one committed and incremented new_total)
    # gets a fresh reservation.
    idem_key = (
        f"flashbuy:{user.id}:{fs.id}:{fs_item.variant_id}:{new_total}"
    )
    try:
        reserve_resp = await stub.ReserveStock(
            pb.ReserveStockRequest(
                idempotency_key=idem_key,
                user_id=user.id,
                items=[
                    pb.StockItem(
                        variant_id=fs_item.variant_id, quantity=payload.quantity
                    )
                ],
                ttl_seconds=300,
            )
        )
    except grpc.aio.AioRpcError as exc:
        await redis.decrby(counter_key, payload.quantity)
        # The inventory service has its own (independently bucketed)
        # rate limit. Translate its RESOURCE_EXHAUSTED to a clean 429
        # rather than letting the AioRpcError surface as a 500.
        if exc.code() == grpc.StatusCode.RESOURCE_EXHAUSTED:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Inventory rate-limited: {exc.details()}",
                headers={"Retry-After": "10"},
            )
        raise
    if not reserve_resp.success:
        await redis.decrby(counter_key, payload.quantity)
        logger.info(
            "flash_sale_attempt: fsid=%s vid=%s user=%s qty=%s status=rejected reason=%s",
            fs.id,
            fs_item.variant_id,
            user.id,
            payload.quantity,
            reserve_resp.error,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Insufficient stock: {reserve_resp.error}",
        )
    reservation_id = reserve_resp.reservation_id

    # --- 6. Persist Order + Payment at the flash-sale price ---
    line_total = fs_item.sale_price * payload.quantity
    subtotal = line_total
    shipping_fee = Decimal("0")
    total = subtotal + shipping_fee

    try:
        order = Order(
            user_id=user.id,
            address_id=address.id,
            status=OrderStatus.PENDING,
            subtotal=subtotal,
            shipping_fee=shipping_fee,
            total=total,
            flash_sale_id=fs.id,
            items=[
                OrderItem(
                    variant_id=fs_item.variant_id,
                    quantity=payload.quantity,
                    unit_price=fs_item.sale_price,
                    line_total=line_total,
                )
            ],
        )
        db.add(order)
        await db.flush()

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
        await redis.decrby(counter_key, payload.quantity)
        await stub.ReleaseReservation(pb.ReleaseRequest(reservation_id=reservation_id))
        raise

    # --- 7. Observability hook (Step 11 will write ClickHouse here) ---
    logger.info(
        "flash_sale_attempt: fsid=%s vid=%s user=%s qty=%s order=%s status=accepted",
        fs.id,
        fs_item.variant_id,
        user.id,
        payload.quantity,
        order.id,
    )

    # --- 8. Reload with eager relationships for the response ---
    fresh = await db.scalar(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.payment))
        .where(Order.id == order.id)
    )
    return OrderOut.model_validate(fresh)
