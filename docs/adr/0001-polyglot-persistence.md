# ADR 0001 — Polyglot persistence: Postgres + Redis + Meilisearch + ClickHouse

- **Status:** Accepted
- **Date:** 2026-02-15
- **Owner:** M3 (Data Engineer)

## Context

Rubric requirement R5 demands non-relational stores alongside Postgres,
and explicitly warns that "decorative polyglot" (a Redis instance only
used as a session cache, for instance) gets zero credit. Each
non-relational store must justify itself with a workload that the
relational alternative cannot handle adequately.

The flash-sale scenario also imposes three concrete pressures:

1. Hundreds of writes per second decrementing the same stock row
   would deadlock Postgres at the row-lock level.
2. Typo-tolerant catalogue search with facets is a poor fit for
   Postgres GIN — facets in particular need separate index roundtrips
   per facet field.
3. Analytics over hundreds of thousands of flash-sale events need to
   run in single-digit-second OLAP latency on a 4 GB droplet — row-
   store Postgres aggregations OOM at much smaller scale.

## Decision

Four data stores, each scoped to a workload it is uniquely good at:

| Store | Workload | Why not Postgres |
|---|---|---|
| **Postgres 16** | Catalog, orders, users, payments, audit | The system of record. |
| **Redis 7** | `stock:{vid}` counters, `cart:{uid}` hashes, token-bucket state, `hot:product:{id}` cache | Atomic single-key ops at sub-ms latency; no row locks under contention. |
| **Meilisearch 1.10** | Product catalogue search with typo tolerance + facets | Postgres `ILIKE '%q%'` cannot use B-tree; GIN trigram doesn't do facets without per-field index round-trips. R6 measured 2.7× lower p50 (349 ms vs 957 ms). |
| **ClickHouse 24.8** | `flash_sale_events` + `order_events` + materialised views | Columnar aggregation over millions of events at interactive latency on the droplet; row-store Postgres analytics queries OOM. |

A single Postgres row is the durable record for stock
(`inventory_levels`), but the **Redis counter is authoritative during
flash sales** and is reconciled back to Postgres after each sale ends.
Carts are similar: `carts` is the durable record, `cart:{uid}` is the
live working state.

## Consequences

**Positive**

- Each store does what it's best at; no impedance mismatches.
- R6 measurements gave headline numbers: 4.3× product detail, 2.7× search.
- Real polyglot story to defend in the viva.

**Negative**

- Four data stores to operate, back up, and observe.
- Reconciliation logic (Redis → Postgres for stock) is non-trivial.
- ClickHouse on 4 GB droplet is tight; would not survive a true
  production workload without dedicated nodes.

## Alternatives considered

- **Postgres for everything.** Tested in R6 baseline runs — search and
  flash-sale decrement collapse under load.
- **DynamoDB or another KV.** Adds vendor lock-in and moves us off the
  IaaS Docker Compose stack the spec requires.
- **Elasticsearch instead of Meilisearch.** Heavier (JVM, GB+ heap),
  overkill for ~1000 products, slower index time, more operational
  surface.
