"""Async Redis client and cart-key helpers.

The Postgres ``carts`` / ``cart_items`` tables are the durable record,
but the *live* working cart sits in Redis as a hash for O(1) field-level
mutations and to keep transient activity off the relational tier.

Hash layout used by the cart router::

    HSET cart:{user_id} {variant_id} {quantity}

A single shared async client is opened in the FastAPI lifespan and
reused across requests. Connection pooling is handled internally by
``redis-py``.
"""
from __future__ import annotations

from redis.asyncio import Redis

from app.config import get_settings

# 7 days — covers a normal browsing session without pinning idle data forever.
CART_TTL_SECONDS: int = 7 * 24 * 3600

_client: Redis | None = None


def get_cart_key(user_id: int) -> str:
    return f"cart:{user_id}"


def get_cart_lock_key(user_id: int) -> str:
    """Reserved for Step 9 (checkout) to serialise cart mutations against
    order creation. Defined here so callers import keys from one place."""
    return f"cart_lock:{user_id}"


def _build_url() -> str:
    s = get_settings()
    return f"redis://{s.redis_host}:{s.redis_port}/0"


async def init_redis() -> None:
    """Open the shared client and verify connectivity once at startup."""
    global _client
    if _client is not None:
        return
    _client = Redis.from_url(_build_url(), decode_responses=True)
    # Fail fast if Redis is unreachable — the compose healthcheck makes
    # this very unlikely, but a clear error here beats a 500 on first hit.
    await _client.ping()


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def get_redis() -> Redis:
    """FastAPI dependency yielding the shared async client.

    Lazy-initialises if the lifespan handler hasn't run yet (one-off
    scripts, ad-hoc imports). Normal request traffic always hits the
    lifespan path first."""
    if _client is None:
        await init_redis()
    assert _client is not None
    return _client
