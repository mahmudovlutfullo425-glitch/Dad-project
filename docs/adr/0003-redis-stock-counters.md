# ADR 0003 — Redis as source-of-truth for flash-sale stock

- **Status:** Accepted
- **Date:** 2026-03-08
- **Owner:** M4 (Systems Engineer)

## Context

Flash sales are the scenario's defining workload. A typical sale
allocates 20 items at 40 % off, drops at a published moment, and
attracts hundreds of users hitting `POST /flashsales/{id}/buy`
simultaneously. The stock-decrement code path is on the hot path of
every one of those requests.

Trying to keep `inventory_levels.quantity_on_hand` authoritative in
Postgres during the sale would mean either:

- `SELECT ... FOR UPDATE` on the variant row — every concurrent
  reservation serialises on the row lock; throughput collapses to
  ~connection-pool size divided by lock-hold time, and the pool
  saturates almost immediately under 500 VUs.
- Optimistic concurrency with a CAS loop — works but spawns large
  numbers of retries under high contention and still hits the
  connection pool ceiling.

R6 measurements demonstrate this: the Postgres `SELECT ... FOR UPDATE`
backend can sustain about 27 accepted orders/sec at 500 VUs; the
underlying issue is that the connection pool (5 + 10 overflow) is the
limit, not Postgres throughput per se.

## Decision

During an active flash sale, the **authoritative stock counter is a
Redis key `stock:{variant_id}`**, not the Postgres `inventory_levels`
row.

- On inventory-service start, a bootstrap step reads
  `inventory_levels` and writes `stock:{vid}` = `quantity_on_hand
  − quantity_reserved` for every variant. A Redis lock prevents the
  two-replica race.
- `ReserveStock` uses a **Lua script** (`DECRBY` + rollback on partial
  failure) so a single round-trip is atomic across multiple
  variants.
- `CommitReservation` writes the changes back to Postgres
  (`inventory_levels.quantity_on_hand -= qty`) and deletes the
  reservation key.
- `ReleaseReservation` `INCRBY`s the counter back if the order is
  cancelled or times out.
- A reconciliation pass (Celery beat) sweeps Redis ↔ Postgres after
  the sale ends.

## Consequences

**Positive**

- Redis single-threaded executor turns concurrent decrements into a
  microsecond-level queue — no row locks, no connection-pool pressure.
- The architectural argument is sound and defensible in the viva.
- Decoupling lets us measure each backend independently
  (`USE_POSTGRES_STOCK` env flag in inventory).

**Negative**

- Redis is in-memory only — a redis crash before the post-sale
  reconciliation loses any partial-sale stock state. Mitigated by
  `--appendonly yes`, but the AOF still has a flush window.
- The reconciliation step adds complexity to the system.
- Operators must remember the two-layer model (Redis is authoritative
  during sales; Postgres is authoritative otherwise).

## Alternatives considered

- **Pure Postgres with `SELECT ... FOR UPDATE`.** Measured in R6 —
  see `docs/measurements/README.md`.
- **Postgres with optimistic concurrency.** Still hits the
  connection-pool ceiling under 500 VUs.
- **Etcd / Consul as the atomic store.** Heavier, more operational
  surface, no measurable advantage over Redis Lua.
