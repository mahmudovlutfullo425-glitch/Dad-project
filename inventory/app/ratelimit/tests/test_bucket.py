"""Unit tests for the pure-Python TokenBucket.

These tests don't touch Redis. They drive the Python reference
implementation directly so the algorithm's edge cases are pinned
in code. The Lua version (``bucket.lua``) mirrors the same logic
and is covered separately in ``test_redis_backend.py``.
"""
import math

from app.ratelimit.bucket import TokenBucket


def test_new_bucket_is_full():
    """A freshly-created bucket holds its full capacity."""
    b = TokenBucket.new(capacity=5, refill_rate=1.0, now=100.0)
    assert b.tokens == 5.0
    assert b.last_refill == 100.0


def test_single_consume_succeeds_and_decrements():
    b = TokenBucket.new(capacity=5, refill_rate=1.0, now=100.0)
    assert b.try_consume(1, now=100.0) is True
    assert b.tokens == 4.0


def test_consume_more_than_capacity_fails():
    b = TokenBucket.new(capacity=3, refill_rate=1.0, now=100.0)
    assert b.try_consume(4, now=100.0) is False
    # Bucket state is unchanged on a rejection.
    assert b.tokens == 3.0


def test_exhausting_then_failing_to_consume():
    b = TokenBucket.new(capacity=2, refill_rate=1.0, now=100.0)
    assert b.try_consume(1, now=100.0) is True
    assert b.try_consume(1, now=100.0) is True
    assert b.try_consume(1, now=100.0) is False
    assert b.tokens == 0.0


def test_refill_over_time():
    """Two tokens over 2 seconds at 1 token/s — exact refill, no overflow."""
    b = TokenBucket.new(capacity=5, refill_rate=1.0, now=100.0)
    # Drain to zero
    b.try_consume(5, now=100.0)
    assert b.tokens == 0.0
    # Two seconds pass
    b.refill(now=102.0)
    assert b.tokens == 2.0


def test_refill_caps_at_capacity():
    """A bucket can never exceed its capacity, no matter how long
    it has been idle."""
    b = TokenBucket.new(capacity=5, refill_rate=1.0, now=100.0)
    b.refill(now=10_000.0)  # ~3 hours later
    assert b.tokens == 5.0


def test_clock_skew_does_not_overflow():
    """If `now` jumps backwards (e.g. NTP step on another replica),
    we must not refund tokens. Elapsed is clamped to zero."""
    b = TokenBucket.new(capacity=5, refill_rate=1.0, now=100.0)
    b.try_consume(3, now=100.0)
    assert b.tokens == 2.0
    # Clock goes backwards.
    b.refill(now=99.0)
    assert b.tokens == 2.0  # unchanged
    # last_refill still updates so subsequent forward-progress measures
    # from the latest observation, not the original.
    assert b.last_refill == 99.0


def test_fractional_refill_rate():
    """0.5 tokens/sec — after 1 second we have 0.5 token added."""
    b = TokenBucket.new(capacity=10, refill_rate=0.5, now=100.0)
    b.try_consume(10, now=100.0)
    b.refill(now=101.0)
    assert math.isclose(b.tokens, 0.5)
    # Need at least 1 token to consume — 0.5 isn't enough.
    assert b.try_consume(1, now=101.0) is False
    # Another full second gets us to 1.0 → just barely enough.
    b.refill(now=102.0)
    assert math.isclose(b.tokens, 1.0)
    assert b.try_consume(1, now=102.0) is True


def test_retry_after_seconds():
    """When a consume fails, retry_after reports the wait until
    `n` tokens accumulate at the configured refill rate."""
    b = TokenBucket.new(capacity=5, refill_rate=0.5, now=100.0)
    b.try_consume(5, now=100.0)  # drain
    # Needs 1 token at 0.5/s = 2 seconds.
    assert math.isclose(b.retry_after(1), 2.0)


def test_retry_after_returns_inf_when_refill_disabled():
    """refill_rate=0 is a "this bucket is closed" signal — retry_after
    must surface that clearly rather than divide-by-zero."""
    b = TokenBucket.new(capacity=1, refill_rate=0.0, now=100.0)
    b.try_consume(1, now=100.0)
    assert b.retry_after(1) == float("inf")


def test_burst_then_steady_state():
    """Realistic flash-buy-per-user shape: 3-token burst, 0.1/s refill.
    First 3 try_consumes pass instantly; the 4th has to wait 10s."""
    b = TokenBucket.new(capacity=3, refill_rate=0.1, now=0.0)
    assert b.try_consume(1, now=0.1) is True
    assert b.try_consume(1, now=0.2) is True
    assert b.try_consume(1, now=0.3) is True
    assert b.try_consume(1, now=0.4) is False
    # 10 seconds after first burst, one token is back.
    assert b.try_consume(1, now=10.3) is True
