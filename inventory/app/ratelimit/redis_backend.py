"""Distributed token-bucket store backed by Redis + Lua.

The single ``try_consume`` call is one EVALSHA round trip. Refill,
threshold check, and decrement happen inside Redis as a single
command, so there is no GET / compute / SET race.

``RedisBucketStore`` is the only place the Lua script is loaded.
NOSCRIPT (Redis restarted, script cache flushed) triggers a
transparent SCRIPT LOAD + retry.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from redis.asyncio import Redis
from redis.exceptions import NoScriptError

# Load the Lua source at import time. The file ships next to this
# module in the Python package, so __file__-relative is the right
# lookup regardless of where the process is launched from.
_LUA_PATH = Path(__file__).parent / "bucket.lua"
BUCKET_LUA = _LUA_PATH.read_text(encoding="utf-8")


@dataclass(frozen=True)
class RateLimitResult:
    """Outcome of a single try_consume call.

    ``retry_after_seconds`` is a float (sub-second precision) so the
    caller can decide whether to surface it as an integer
    ``Retry-After`` header or as a more precise diagnostic."""

    allowed: bool
    remaining: int
    retry_after_seconds: float


class RedisBucketStore:
    """Atomic token-bucket store. Thread-safe; share one instance
    across the whole process."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._sha: str | None = None

    async def _ensure_loaded(self) -> str:
        if self._sha is None:
            self._sha = await self._redis.script_load(BUCKET_LUA)
        return self._sha

    async def try_consume(
        self,
        key: str,
        capacity: int,
        refill_rate: float,
        tokens: int = 1,
    ) -> RateLimitResult:
        """Attempt to spend ``tokens`` from the bucket at ``key``.

        Resilient to Redis being flushed of cached scripts: a
        ``NOSCRIPT`` error triggers SCRIPT LOAD and a single retry."""
        sha = await self._ensure_loaded()
        now = time.time()
        args = [
            str(capacity),
            str(refill_rate),
            f"{now:.6f}",
            str(tokens),
        ]
        try:
            result = await self._redis.evalsha(sha, 1, key, *args)
        except NoScriptError:
            # Redis dropped its script cache (restart, SCRIPT FLUSH,
            # etc.). Reload and try once more — only once: a second
            # NoScriptError would indicate something stranger and we
            # surface it.
            self._sha = await self._redis.script_load(BUCKET_LUA)
            result = await self._redis.evalsha(self._sha, 1, key, *args)

        allowed = int(result[0]) == 1
        remaining = int(result[1])
        retry_after_ms = int(result[2])
        return RateLimitResult(
            allowed=allowed,
            remaining=remaining,
            retry_after_seconds=retry_after_ms / 1000.0,
        )
