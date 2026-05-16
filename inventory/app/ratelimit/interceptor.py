"""gRPC server interceptor — applies token-bucket rules to inventory RPCs.

A single rule (FLASH_BUY_PER_USER) is wired today against
``Inventory.ReserveStock``. The interceptor extracts ``user_id``
from the request message itself: gRPC is a trusted service-to-
service hop, so the api has already authenticated the caller
upstream and forwards the user identity as a field.

Fail-open semantics match the FastAPI middleware: if Redis throws,
we log and allow the request through. The hard limit is enforced
inside the Lua DECRBY in the inventory ReserveStock script
(stock can never go negative regardless of how many requests get
past this interceptor).

Prometheus counters declared in :mod:`app.observability` are
incremented here so the same dashboard panels work for both the
edge (FastAPI middleware) and the service-to-service hop.
"""
from __future__ import annotations

import logging

import grpc

from app.config import get_settings
from app.observability import RATE_LIMIT_ALLOWED, RATE_LIMIT_REJECTED
from app.ratelimit.config import RULES, RateLimitRule
from app.ratelimit.redis_backend import RedisBucketStore

logger = logging.getLogger(__name__)


# Mapping from full gRPC method path to the rule name applied.
# Add entries here to extend rate-limiting to other RPCs.
METHOD_RULES: dict[str, str] = {
    "/inventory.Inventory/ReserveStock": "FLASH_BUY_PER_USER",
}


class RateLimitInterceptor(grpc.aio.ServerInterceptor):
    """Server-side aio interceptor for unary RPCs.

    Streaming RPCs aren't currently rate-limited because none of
    ours are streaming. If you add one, extend the wrapper to
    handle it before the unary fall-through."""

    def __init__(self, store: RedisBucketStore) -> None:
        self._store = store

    async def intercept_service(self, continuation, handler_call_details):
        method = handler_call_details.method
        rule_name = METHOD_RULES.get(method)
        if rule_name is None:
            return await continuation(handler_call_details)

        rule = RULES[rule_name]
        handler = await continuation(handler_call_details)
        if handler is None:
            return None

        # Unary-unary is the only mode we wrap. Streaming endpoints
        # fall through unchanged.
        if handler.request_streaming or handler.response_streaming:
            return handler

        inner = handler.unary_unary

        async def wrapped(request, context: grpc.aio.ServicerContext):
            # Short-circuit when measurement runs disable the limiter.
            # Re-checked per request so an env flip takes effect on
            # the next call without needing to recreate handlers.
            if not get_settings().rate_limit_enabled:
                return await inner(request, context)

            user_id = getattr(request, "user_id", 0) or 0
            # Namespace the bucket with "grpc:" so this internal-hop
            # rate limit doesn't share a counter with the api-edge
            # one. Both layers use the same rule (capacity + refill)
            # but each gets its own bucket — defense in depth, no
            # double-billing of tokens per user request.
            key = f"bucket:grpc:{rule.name}:{user_id}"

            try:
                result = await self._store.try_consume(
                    key, rule.capacity, rule.refill_rate
                )
            except Exception as exc:
                # Fail-open: log, allow. Hard inventory limits still
                # apply downstream in the Lua DECRBY path.
                logger.warning(
                    "rate-limit Redis error on %s for user=%s: %s",
                    method,
                    user_id,
                    exc,
                )
                return await inner(request, context)

            if not result.allowed:
                RATE_LIMIT_REJECTED.labels(rule=rule.name).inc()
                await context.abort(
                    grpc.StatusCode.RESOURCE_EXHAUSTED,
                    (
                        f"rate limited ({rule.name}); "
                        f"retry after {result.retry_after_seconds:.1f}s"
                    ),
                )

            RATE_LIMIT_ALLOWED.labels(rule=rule.name).inc()
            return await inner(request, context)

        return grpc.unary_unary_rpc_method_handler(
            wrapped,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
