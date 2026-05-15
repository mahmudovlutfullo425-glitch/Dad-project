"""Integration tests for the Redis-backed (Lua) token bucket.

Run inside the inventory container so ``redis://redis:6379`` resolves
to the shared compose-network Redis. The fixture uses DB 15 to keep
test state isolated from the real services on DB 0, and flushes
before and after each test.
"""
import asyncio

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.ratelimit.redis_backend import RedisBucketStore


@pytest_asyncio.fixture
async def redis():
    """Per-test Redis connection on DB 15 (isolated from real workload)."""
    r = Redis.from_url("redis://redis:6379/15", decode_responses=True)
    await r.flushdb()
    yield r
    await r.flushdb()
    await r.aclose()


@pytest_asyncio.fixture
async def store(redis):
    return RedisBucketStore(redis)


@pytest.mark.asyncio
async def test_first_call_returns_allowed_with_full_bucket(store):
    result = await store.try_consume("test:bucket:user:1", capacity=5, refill_rate=1.0)
    assert result.allowed is True
    # capacity 5 minus the one we just spent.
    assert result.remaining == 4
    assert result.retry_after_seconds == 0.0


@pytest.mark.asyncio
async def test_drain_then_reject(store):
    key = "test:drain:user:1"
    for _ in range(3):
        result = await store.try_consume(key, capacity=3, refill_rate=0.1)
        assert result.allowed is True

    rejected = await store.try_consume(key, capacity=3, refill_rate=0.1)
    assert rejected.allowed is False
    assert rejected.remaining == 0
    # 0.1 tokens/s means a single-token wait is ~10s.
    assert rejected.retry_after_seconds > 5.0


@pytest.mark.asyncio
async def test_refill_after_wait(store):
    """Drain a bucket, wait long enough for a token to appear, retry."""
    key = "test:refill:user:1"
    capacity, refill = 2, 5.0  # refill twice per second

    await store.try_consume(key, capacity, refill)
    await store.try_consume(key, capacity, refill)
    rejected = await store.try_consume(key, capacity, refill)
    assert rejected.allowed is False

    # Wait long enough for 1+ token to refill (5/sec → 1 token in 0.2s).
    await asyncio.sleep(0.3)
    allowed = await store.try_consume(key, capacity, refill)
    assert allowed.allowed is True


@pytest.mark.asyncio
async def test_independent_keys_dont_share_state(store):
    """Two different bucket keys are independent — exhausting one
    has no effect on the other."""
    for _ in range(2):
        await store.try_consume("k1", capacity=2, refill_rate=0.1)
    rejected = await store.try_consume("k1", capacity=2, refill_rate=0.1)
    assert rejected.allowed is False

    fresh = await store.try_consume("k2", capacity=2, refill_rate=0.1)
    assert fresh.allowed is True


@pytest.mark.asyncio
async def test_noscript_recovery(store, redis):
    """If Redis's script cache is flushed mid-flight, the store must
    transparently SCRIPT LOAD and retry rather than failing the call."""
    # Prime the cache.
    await store.try_consume("test:noscript", capacity=3, refill_rate=1.0)

    # Drop every loaded script. The store still has its cached SHA.
    await redis.script_flush()

    # Next call would EVALSHA against a missing script — store must recover.
    result = await store.try_consume("test:noscript", capacity=3, refill_rate=1.0)
    assert result.allowed is True
