# ADR 0002 — Token-bucket rate limiter from scratch (R11)

- **Status:** Accepted
- **Date:** 2026-03-02
- **Owner:** M4 (Systems Engineer)

## Context

Rubric requirement R11 demands a system-design component implemented
from scratch and integrated into the running system. The component is
worth 15 % of the total grade (10 % implementation + 5 % writeup) and
the viva will probe it deeply.

The flash-sale workload also genuinely needs rate limiting:

- **Per-user limit** on `/flashsales/{id}/buy` to stop one user
  grabbing all the stock with a bot.
- **Per-IP limit** on `/auth/login` to mitigate credential stuffing.
- **Global limit** on `/checkout/*` to protect the inventory service
  from a stampede.

## Decision

A pure-Python **token-bucket** algorithm, with Redis-backed shared
state for distributed coordination across the two API replicas, and a
**Lua script** for atomic refill-and-consume.

Four named rules (in `app/ratelimit/config.py`):

| Rule | Capacity | Refill | Scope |
|---|---|---|---|
| `FLASH_BUY_PER_USER` | 3 | 0.1/s | user |
| `LOGIN_PER_IP` | 5 | 0.05/s | IP |
| `CHECKOUT_GLOBAL` | 1000 | 200/s | global |
| `API_PER_USER_DEFAULT` | 60 | 1/s | user |

The same code ships as both **FastAPI middleware** (for HTTP routes)
and **gRPC interceptor** (for the inventory service).

## Consequences

**Positive**

- Bursts are allowed (token bucket vs leaky bucket) — better UX during
  a flash sale where a user clicks twice quickly.
- Lua atomicity means no race on refill-and-consume across replicas.
- The same algorithm protects both HTTP and gRPC surfaces with one
  implementation.

**Negative**

- Fail-open on Redis unreachability (logged + Prometheus counter) — a
  Redis outage means the soft cap stops working. Accepted because
  hard limits live in the inventory service's atomic stock counters.
- Single Redis instance is a SPOF; sharding by key prefix is possible
  but unnecessary at coursework scale.

## Alternatives considered

- **Leaky bucket.** Smooths bursts away; feels unresponsive for users
  who click the buy button twice in quick succession.
- **Fixed window counter.** Boundary effects allow a 2× burst around
  window boundaries (last second of window N + first second of N+1).
- **Use an off-the-shelf library** (`slowapi`, `fastapi-limiter`).
  Would zero R11 — the spec explicitly requires a from-scratch
  implementation that every team member can defend.
