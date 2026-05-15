"""Token-bucket rate limiter (R11 — the headline from-scratch component).

The algorithm is implemented twice: a pure-Python reference
(``bucket.py``) used by the unit tests, and an atomic Lua version
(``bucket.lua``, executed via ``redis_backend.RedisBucketStore``)
that enforces the limit across all replicas through Redis as a
shared clock and shared state.

Integration points:

- ``interceptor.py`` — gRPC ServerInterceptor that protects
  ``Inventory.ReserveStock`` (per-user scope) in this service.
- ``../../api/app/ratelimit/middleware.py`` — FastAPI dependency
  factory mirroring the same rules from the api side.

The R11 writeup defends *token bucket vs leaky bucket vs fixed
window* and *Lua atomicity vs GET/SET race*. See the report for
the full discussion.
"""
