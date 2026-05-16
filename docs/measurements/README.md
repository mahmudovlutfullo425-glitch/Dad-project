# R6 — Measured optimisation results

This directory documents the three before/after measurements required
by **R6 (Cache + index + measurable optimisation, 7%)** in the rubric.
Each measurement compares a *naive* implementation against the
optimised one currently used in production, with real
[k6](https://k6.io/) latency numbers, not hand-waving.

The three comparisons:

| # | Scenario | Naive (before) | Optimised (after) | Test script |
|---|---|---|---|---|
| 1 | Product detail read | Postgres on every request | Redis hot cache (`hot:product:{id}`, TTL 300s) | [`product_detail.js`](../../scripts/loadtest/product_detail.js) |
| 2 | Catalogue search | Postgres `ILIKE '%q%'` (full scan) | Meilisearch typo-tolerant + facets | [`search_compare.js`](../../scripts/loadtest/search_compare.js) |
| 3 | Flash-sale stock decrement | Postgres `SELECT ... FOR UPDATE` + UPDATE | Atomic Redis Lua `DECRBY` | [`flash_sale.js`](../../scripts/loadtest/flash_sale.js) |

## How the switch works (no code duplication)

Both modes ship in the same codebase. Three environment flags toggle
the implementation under test:

| Flag | Default | Purpose |
|---|---|---|
| `PRODUCT_CACHE_ENABLED` | `true` | Set to `false` for the product-detail baseline run. Cache code path is skipped entirely — every request goes to Postgres. |
| `USE_POSTGRES_STOCK` | `false` | Set to `true` for the flash-sale baseline run. `ReserveStock` switches to `SELECT ... FOR UPDATE` on `inventory_levels`. Commit/Release follow suit so the lifecycle stays correct. |
| `RATE_LIMIT_ENABLED` | `true` | Set to `false` for every load test. Without this, `FLASH_BUY_PER_USER` (capacity 3) would 429 most of the 500 VUs immediately and the test would measure rate-limit rejections instead of the stock backend. |

All three are honoured at request time (settings cached via
`@lru_cache`, re-read once per process restart). Flipping a flag
requires a `docker compose restart` of the affected service for the
new value to take effect.

## Reproducing the measurements

### Prerequisites

- Stack is up and seeded (`make up && make seed && make reindex`).
- `k6` is available either as `docker run grafana/k6` (no host install
  needed) or natively on the host. The Make targets use the Docker
  variant — they pass `--network` so k6 joins the `ecom-net` bridge
  and resolves `gateway` by name.

### One command per scenario

```bash
make k6-product-detail-baseline      # ① cache disabled, 100 VUs × 60s
make k6-product-detail-cached        # ① cache enabled,  100 VUs × 60s

make k6-search-compare               # ② runs ILIKE then Meilisearch back-to-back

make loadtest-flashsale              # ③ one-off: refresh the active flash sale
make k6-flash-sale-postgres          # ③ SELECT ... FOR UPDATE, 500 VUs × 30s
make k6-flash-sale-redis             # ③ Redis Lua DECRBY,     500 VUs × 30s

make k6-all                          # all three back-to-back (≈ 5 min wall clock)
```

Each run writes a self-contained summary into
[`runs/`](runs/), one JSON file per run, named with the scenario
+ mode + timestamp. The summary contains `http_req_duration` quantiles
plus per-scenario custom trends (e.g. `flash_sale_buy_latency_ms{p95}`).

### Cleaning up after a flash-sale load run

A full 30-second 500-VU run can place tens of thousands of small
`PENDING` orders against the load-test flash sale. None block
correctness, but to keep `orders` tidy:

```bash
make db-shell
> DELETE FROM order_items WHERE order_id IN (
>   SELECT id FROM orders WHERE flash_sale_id = <id-from-create-loadtest-flashsale-output>
> );
> DELETE FROM payments WHERE order_id IN (
>   SELECT id FROM orders WHERE flash_sale_id = <id>
> );
> DELETE FROM orders WHERE flash_sale_id = <id>;
```

`create_loadtest_flashsale.py` is itself idempotent, so re-running it
before the next test only needs to bump the window.

## Results

> **TODO**: fill in the table below from `runs/` after a fresh run on
> the deploy droplet. Numbers from a developer laptop are
> indicative but should not be reported — the report compares them
> against the NFR targets (500 RPS sustained, p95 < 200 ms browse).

| Scenario | Metric | Baseline (naive) | Optimised | Improvement |
|---|---|---|---|---|
| ① Product detail | p50 | _TBD_ ms | _TBD_ ms | _TBDx_ |
| ① Product detail | p95 | _TBD_ ms | _TBD_ ms | _TBDx_ |
| ① Product detail | p99 | _TBD_ ms | _TBD_ ms | _TBDx_ |
| ① Product detail | RPS | _TBD_ | _TBD_ | _TBDx_ |
| ② Catalogue search | p50 | _TBD_ ms | _TBD_ ms | _TBDx_ |
| ② Catalogue search | p95 | _TBD_ ms | _TBD_ ms | _TBDx_ |
| ② Catalogue search | p99 | _TBD_ ms | _TBD_ ms | _TBDx_ |
| ② Catalogue search | RPS | _TBD_ | _TBD_ | _TBDx_ |
| ③ Flash-sale decrement | p50 | _TBD_ ms | _TBD_ ms | _TBDx_ |
| ③ Flash-sale decrement | p95 | _TBD_ ms | _TBD_ ms | _TBDx_ |
| ③ Flash-sale decrement | p99 | _TBD_ ms | _TBD_ ms | _TBDx_ |
| ③ Flash-sale decrement | Accepted/30s | _TBD_ | _TBD_ | _TBDx_ |
| ③ Flash-sale decrement | 5xx rate | _TBD_ % | _TBD_ % | — |

### Where the gains come from

- **Product detail.** With caching off, every read paid the cost of
  one round-trip to Postgres plus two `selectinload`s (category +
  variants). With caching on, the hot path is a single Redis `GET`
  returning a pre-serialised JSON blob. Postgres only sees the cache
  misses, which are ≤ 1000/`TTL` regardless of request rate.
- **Catalogue search.** The naive endpoint runs `name ILIKE '%q%'`
  against `products` — the leading wildcard forbids B-tree index use,
  so it's a full scan plus a JOIN+`selectinload` on each row.
  Meilisearch returns pre-tokenised, ranked, faceted hits from an
  inverted index in single-digit ms.
- **Flash-sale decrement.** `SELECT ... FOR UPDATE` serialises every
  concurrent reservation on the same row — under 500 VUs hammering one
  variant, Postgres throughput collapses to ~connection-pool size
  divided by lock-hold time, and the connection pool (5 + 10 overflow)
  saturates almost immediately. Redis Lua runs in Redis's single-
  threaded executor, so every reserve is atomic by construction but
  takes microseconds and doesn't queue.

### Validity caveats (for the viva)

- Same hardware between runs (single droplet, no other tenants).
- Same warm state between runs (skip the first 5 s with `--summary-trend-stats`).
- Both Postgres-stock and Redis-stock runs hit the same Postgres
  instance for the auth lookup, the address fetch, and the order
  persist — so the *baseline* relative comparison is honest even if
  the absolute numbers are sensitive to droplet noise.
- The flash-sale `quantity_allocated` and `per_user_limit` are set
  to artificial buffers (1 000 000 each) so neither becomes the
  bottleneck under test — the load test measures the decrement, not
  policy enforcement.

## Files

- [`../../scripts/loadtest/product_detail.js`](../../scripts/loadtest/product_detail.js)
- [`../../scripts/loadtest/search_compare.js`](../../scripts/loadtest/search_compare.js)
- [`../../scripts/loadtest/flash_sale.js`](../../scripts/loadtest/flash_sale.js)
- [`../../scripts/create_loadtest_flashsale.py`](../../scripts/create_loadtest_flashsale.py)
- `runs/` — k6 summary JSONs from each invocation
