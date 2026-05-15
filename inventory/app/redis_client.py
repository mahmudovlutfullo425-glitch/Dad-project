"""Async Redis client for the inventory service.

Same Redis logical database (0) as the api service — counters under
``stock:{variant_id}`` are read by both. The api owns cart, the
inventory service owns stock; the keyspaces don't collide.
"""
from __future__ import annotations

from redis.asyncio import Redis

from app.config import get_settings

_client: Redis | None = None


async def init_redis() -> None:
    global _client
    if _client is not None:
        return
    s = get_settings()
    _client = Redis.from_url(
        f"redis://{s.redis_host}:{s.redis_port}/0",
        decode_responses=True,
    )
    await _client.ping()


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def get_redis() -> Redis:
    if _client is None:
        await init_redis()
    assert _client is not None
    return _client
