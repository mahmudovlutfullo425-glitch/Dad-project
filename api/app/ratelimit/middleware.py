"""FastAPI dependency factory for token-bucket rate limiting.

Spec calls this "middleware", but the example wires it via
``Depends(rate_limit(...))`` — that's a per-endpoint *dependency*,
which is the right primitive: FastAPI middleware runs before the
router knows which endpoint will handle the request, so it can't
look up endpoint-specific rules without re-implementing the router.

Three scopes, three sub-dependencies:

- ``Scope.USER`` — requires authenticated routes; pulls user_id
  from the existing ``get_current_user`` dependency. FastAPI
  caches dependencies within a request, so the auth check that
  ``get_current_user`` does on the endpoint runs only once.
- ``Scope.IP`` — anonymous routes (login). Uses ``X-Real-IP``
  forwarded by Nginx, falling back to the socket peer.
- ``Scope.GLOBAL`` — a single shared bucket for all callers (e.g.
  ``CHECKOUT_GLOBAL`` to backpressure the inventory service).

Fail-open: if Redis throws, log + count and *allow* the request.
The hard limit lives in the inventory service's Lua DECRBY; this
layer is soft protection.

Prometheus counters are emitted so Step 12's dashboard can chart
rejection rate per rule.
"""
from __future__ import annotations

import logging
from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from prometheus_client import Counter

from app.config import get_settings
from app.deps import get_current_user
from app.models import User
from app.ratelimit.config import RULES, RateLimitRule, Scope
from app.ratelimit.redis_backend import RedisBucketStore

logger = logging.getLogger(__name__)


rate_limit_bypassed_total = Counter(
    "rate_limit_bypassed_total",
    "Rate-limit checks skipped because RATE_LIMIT_ENABLED=false.",
    ["rule"],
)


rate_limit_allowed_total = Counter(
    "rate_limit_allowed_total",
    "Rate-limit checks that allowed the request through.",
    ["rule"],
)
rate_limit_rejected_total = Counter(
    "rate_limit_rejected_total",
    "Rate-limit checks that rejected the request with 429.",
    ["rule"],
)
rate_limit_redis_errors_total = Counter(
    "rate_limit_redis_errors_total",
    "Rate-limit Redis errors (fail-open path taken).",
)


def _get_store(request: Request) -> RedisBucketStore:
    """Fetch the process-wide bucket store from FastAPI app state.

    Populated in the lifespan handler — see api/app/main.py."""
    store = getattr(request.app.state, "bucket_store", None)
    if store is None:
        raise RuntimeError(
            "RedisBucketStore is not on app.state — was lifespan startup run?"
        )
    return store


def _client_ip(request: Request) -> str:
    """Resolve the client IP behind the gateway.

    Nginx sets X-Real-IP / X-Forwarded-For; on a bare ASGI run we
    fall back to the socket peer."""
    forwarded = request.headers.get("X-Real-IP")
    if forwarded:
        return forwarded
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        # Comma-separated chain; the first entry is the original client.
        return xff.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


async def _reject(rule: RateLimitRule, retry_after_seconds: float) -> None:
    """Raise the 429 with a Retry-After header and a structured body."""
    rate_limit_rejected_total.labels(rule=rule.name).inc()
    # Retry-After header is integer seconds per RFC; surface the
    # float retry_after in the body for clients that want precision.
    retry_after_header = max(1, int(retry_after_seconds + 0.999))
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "error": "rate_limited",
            "rule": rule.name,
            "retry_after": retry_after_seconds,
        },
        headers={"Retry-After": str(retry_after_header)},
    )


def rate_limit(rule_name: str) -> Callable:
    """Return a FastAPI dependency that enforces ``rule_name``.

    Usage::

        @router.post(
            "/auth/login",
            dependencies=[Depends(rate_limit("LOGIN_PER_IP"))],
        )
        async def login(...): ...
    """
    if rule_name not in RULES:
        raise KeyError(f"Unknown rate-limit rule: {rule_name}")
    rule = RULES[rule_name]

    if rule.scope == Scope.USER:

        async def _check_user(
            request: Request,
            user: User = Depends(get_current_user),
        ) -> None:
            if not get_settings().rate_limit_enabled:
                rate_limit_bypassed_total.labels(rule=rule.name).inc()
                return
            store = _get_store(request)
            key = rule.key_for(str(user.id))
            try:
                result = await store.try_consume(key, rule.capacity, rule.refill_rate)
            except Exception as exc:
                rate_limit_redis_errors_total.inc()
                logger.warning("rate-limit Redis error on %s: %s", rule.name, exc)
                return
            if not result.allowed:
                await _reject(rule, result.retry_after_seconds)
            rate_limit_allowed_total.labels(rule=rule.name).inc()

        return _check_user

    if rule.scope == Scope.IP:

        async def _check_ip(request: Request) -> None:
            if not get_settings().rate_limit_enabled:
                rate_limit_bypassed_total.labels(rule=rule.name).inc()
                return
            store = _get_store(request)
            key = rule.key_for(_client_ip(request))
            try:
                result = await store.try_consume(key, rule.capacity, rule.refill_rate)
            except Exception as exc:
                rate_limit_redis_errors_total.inc()
                logger.warning("rate-limit Redis error on %s: %s", rule.name, exc)
                return
            if not result.allowed:
                await _reject(rule, result.retry_after_seconds)
            rate_limit_allowed_total.labels(rule=rule.name).inc()

        return _check_ip

    # Scope.GLOBAL
    async def _check_global(request: Request) -> None:
        if not get_settings().rate_limit_enabled:
            rate_limit_bypassed_total.labels(rule=rule.name).inc()
            return
        store = _get_store(request)
        key = rule.key_for(None)
        try:
            result = await store.try_consume(key, rule.capacity, rule.refill_rate)
        except Exception as exc:
            rate_limit_redis_errors_total.inc()
            logger.warning("rate-limit Redis error on %s: %s", rule.name, exc)
            return
        if not result.allowed:
            await _reject(rule, result.retry_after_seconds)
        rate_limit_allowed_total.labels(rule=rule.name).inc()

    return _check_global
