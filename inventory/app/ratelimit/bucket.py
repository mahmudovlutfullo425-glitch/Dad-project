"""Pure-Python token-bucket reference implementation.

The algorithm here MUST match ``bucket.lua`` line-for-line in
behaviour. The Lua version is what actually enforces limits in
production (atomic, shared state across replicas via Redis); the
Python version exists so the report can show the algorithm in a
language anyone can read, and so unit tests can probe edge cases
(refill across an interval, clock skew, exhaustion) without a
Redis dependency.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TokenBucket:
    """Standard token bucket.

    Each call to :meth:`try_consume` first refills based on the
    elapsed time since ``last_refill``, capped at ``capacity``, then
    attempts to spend ``n`` tokens. If the bucket has enough, the
    consume succeeds and the bucket is decremented; otherwise it's
    left as-is and the caller is told to back off.

    Time is passed in explicitly (not read from a clock) so the
    tests can drive deterministic refill scenarios."""

    capacity: int
    refill_rate: float  # tokens per second
    tokens: float
    last_refill: float

    @classmethod
    def new(cls, capacity: int, refill_rate: float, *, now: float) -> "TokenBucket":
        """Construct a fresh, full bucket."""
        return cls(
            capacity=capacity,
            refill_rate=refill_rate,
            tokens=float(capacity),
            last_refill=now,
        )

    def refill(self, now: float) -> None:
        """Advance the bucket to ``now``. Negative ``elapsed`` (clock
        skew between two callers, or a backwards-jumping clock) is
        clamped to zero — we never refund the bucket."""
        elapsed = max(0.0, now - self.last_refill)
        self.tokens = min(
            float(self.capacity),
            self.tokens + elapsed * self.refill_rate,
        )
        self.last_refill = now

    def try_consume(self, n: int, now: float) -> bool:
        """Spend ``n`` tokens if available; return whether it succeeded."""
        self.refill(now)
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False

    def retry_after(self, n: int) -> float:
        """Seconds until ``n`` tokens become available, assuming no
        further consume calls. Used only when ``try_consume`` failed."""
        deficit = n - self.tokens
        if deficit <= 0:
            return 0.0
        if self.refill_rate <= 0:
            return float("inf")
        return deficit / self.refill_rate
