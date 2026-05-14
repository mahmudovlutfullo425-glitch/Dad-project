"""Live cart endpoints — backed by the Redis hash ``cart:{user_id}``.

The Postgres ``carts`` / ``cart_items`` tables become the durable record
only when an order is placed (Step 9) or when an abandoned-cart job
materialises the data (Step 10). Until then, all reads and writes go
straight to Redis.

Hash layout::

    HSET cart:{user_id} {variant_id} {quantity}

A 7-day TTL is refreshed on every operation (reads included) so an
actively-used cart never expires under the user, while an abandoned
one disappears without explicit garbage collection.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import ProductVariant, User
from app.redis_client import CART_TTL_SECONDS, get_cart_key, get_redis
from app.schemas.cart import CartItemIn, CartItemOut, CartItemUpdate, CartOut

router = APIRouter(prefix="/cart", tags=["cart"])


# Per-line cap. Mirrors the Pydantic ``le=999`` on CartItemIn / CartItemUpdate.
MAX_QUANTITY_PER_LINE = 999


async def _touch_ttl(redis: Redis, user_id: int) -> None:
    """Refresh the cart TTL. Safe on a missing key (Redis returns 0)."""
    await redis.expire(get_cart_key(user_id), CART_TTL_SECONDS)


async def _load_active_variant(db: AsyncSession, variant_id: int) -> ProductVariant:
    """Return the variant + parent product, or raise 404 / 400."""
    stmt = (
        select(ProductVariant)
        .options(selectinload(ProductVariant.product))
        .where(ProductVariant.id == variant_id)
    )
    variant = await db.scalar(stmt)
    if variant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Variant {variant_id} not found",
        )
    if not variant.product.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Variant {variant_id} belongs to an inactive product",
        )
    return variant


async def _build_cart_response(
    user_id: int,
    redis: Redis,
    db: AsyncSession,
) -> CartOut:
    """Read the Redis hash, hydrate product info from Postgres, return CartOut."""
    raw: dict[str, str] = await redis.hgetall(get_cart_key(user_id))
    if not raw:
        return CartOut(items=[], subtotal=Decimal("0"), item_count=0)

    quantities: dict[int, int] = {}
    for vid_str, qty_str in raw.items():
        try:
            vid, qty = int(vid_str), int(qty_str)
        except ValueError:
            continue
        if qty > 0:
            quantities[vid] = qty

    if not quantities:
        return CartOut(items=[], subtotal=Decimal("0"), item_count=0)

    # Single round trip for all cart variants. selectinload pulls each
    # variant's parent Product in a follow-up IN query (no N+1).
    stmt = (
        select(ProductVariant)
        .options(selectinload(ProductVariant.product))
        .where(ProductVariant.id.in_(quantities.keys()))
    )
    variants = (await db.scalars(stmt)).all()

    items: list[CartItemOut] = []
    subtotal = Decimal("0")
    for v in variants:
        # Suppress lines whose product has since been deactivated.
        # The Redis state is left alone here — a cleanup job (Step 10)
        # is responsible for pruning stale entries.
        if not v.product.is_active:
            continue
        qty = quantities[v.id]
        line_total = v.price * qty
        items.append(
            CartItemOut(
                variant_id=v.id,
                sku=v.sku,
                name=f"{v.product.name} — {v.variant_name}",
                quantity=qty,
                unit_price=v.price,
                line_total=line_total,
            )
        )
        subtotal += line_total

    items.sort(key=lambda it: it.variant_id)
    # Refresh TTL on read so a browsing user keeps their cart alive.
    await _touch_ttl(redis, user_id)
    return CartOut(
        items=items,
        subtotal=subtotal,
        item_count=sum(it.quantity for it in items),
    )


@router.get(
    "",
    response_model=CartOut,
    summary="Get the authenticated user's cart",
)
async def get_cart(
    user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> CartOut:
    return await _build_cart_response(user.id, redis, db)


@router.post(
    "/items",
    response_model=CartOut,
    status_code=status.HTTP_200_OK,
    summary="Add a variant to the cart (or increment its quantity)",
)
async def add_cart_item(
    payload: CartItemIn,
    user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> CartOut:
    await _load_active_variant(db, payload.variant_id)

    key = get_cart_key(user.id)
    new_qty = await redis.hincrby(key, str(payload.variant_id), payload.quantity)
    if new_qty > MAX_QUANTITY_PER_LINE:
        # Roll the increment back so the user can retry with a smaller qty
        # and we don't leave the cart in an over-cap state.
        await redis.hincrby(key, str(payload.variant_id), -payload.quantity)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Per-line quantity cap ({MAX_QUANTITY_PER_LINE}) exceeded",
        )
    await _touch_ttl(redis, user.id)
    return await _build_cart_response(user.id, redis, db)


@router.patch(
    "/items/{variant_id}",
    response_model=CartOut,
    summary="Set the exact quantity for a cart line (0 removes the line)",
)
async def update_cart_item(
    variant_id: int,
    payload: CartItemUpdate,
    user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> CartOut:
    key = get_cart_key(user.id)
    if payload.quantity == 0:
        await redis.hdel(key, str(variant_id))
    else:
        await _load_active_variant(db, variant_id)
        await redis.hset(key, str(variant_id), str(payload.quantity))
    await _touch_ttl(redis, user.id)
    return await _build_cart_response(user.id, redis, db)


@router.delete(
    "/items/{variant_id}",
    response_model=CartOut,
    summary="Remove a single line from the cart",
)
async def delete_cart_item(
    variant_id: int,
    user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> CartOut:
    key = get_cart_key(user.id)
    await redis.hdel(key, str(variant_id))
    await _touch_ttl(redis, user.id)
    return await _build_cart_response(user.id, redis, db)


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Empty the entire cart",
)
async def clear_cart(
    user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
) -> Response:
    await redis.delete(get_cart_key(user.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
