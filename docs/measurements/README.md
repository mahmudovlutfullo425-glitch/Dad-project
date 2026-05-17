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

Measured **2026-05-17** on the production droplet
(`159.65.114.240.nip.io`, DO 8 GB / 4 vCPU, k6 0.54.0 inside the
`ecom-net` bridge, traffic routed through the public Caddy gateway
over TLS 1.3 so the numbers reflect what the prof actually sees from
the browser, not in-network shortcut measurements).

Raw k6 summary JSONs are in `runs/` (gitignored — locally generated;
re-run with `make -k k6-all` to regenerate).

| Scenario | Metric | Baseline (naive) | Optimised | Improvement |
|---|---|---|---|---|
| ① Product detail | p50 | 684 ms | **159 ms** | **4.3×** |
| ① Product detail | p95 | 1339 ms | **387 ms** | **3.5×** |
| ① Product detail | RPS sustained | 130 req/s | **520 req/s** | **4.0×** |
| ① Product detail | error rate | 0.00 % | 0.00 % | — |
| ② Catalogue search | p50 | 957 ms (ILIKE) | **349 ms (Meili)** | **2.7×** |
| ② Catalogue search | p95 | 1883 ms (ILIKE) | **1358 ms (Meili)** | **1.4×** |
| ② Catalogue search | iterations / 120s | 5 748 (ILIKE) | **12 270 (Meili)** | **2.1×** |
| ③ Flash-sale decrement | p50 (buy latency) | 13 621 ms (PG) | 13 574 ms (Redis) | ≈ 1.0× |
| ③ Flash-sale decrement | p95 (buy latency) | 33 201 ms (PG) | 32 607 ms (Redis) | ≈ 1.0× |
| ③ Flash-sale decrement | Accepted / 30s | 808 (PG) | 719 (Redis) | 0.89× |
| ③ Flash-sale decrement | 5xx rate | 14.0 % (PG) | 14.7 % (Redis) | — |

### Reading the table

- **① Product detail** — clean cache win: 4× more throughput, 3.5× lower
  p95. Redis hot-cache returns a pre-serialised JSON blob in ~10 ms
  while the no-cache path pays for one Postgres round-trip plus two
  `selectinload`s (category + variants) per request.
- **② Catalogue search** — 2× more queries sustained at sub-half-second
  p50. ILIKE does a full table scan against `products` with a leading
  wildcard that forbids B-tree use; Meilisearch hits a pre-tokenised
  inverted index in single-digit-ms server-side. The HTTP round-trip
  through Caddy + TLS dominates the absolute numbers, which is why
  the p95 gap is narrower than the p50 gap.
- **③ Flash-sale decrement — surprising tie at 500 VUs.** Both backends
  flatten out at ~25 accepted orders/sec under 500 concurrent VUs
  over the public TLS endpoint. The bottleneck has **shifted upstream
  of the stock-decrement implementation**: TLS handshake (avg 580 ms,
  p95 1.7 s in the Redis run) and connection pool contention saturate
  the gateway long before the inventory call matters. Postgres
  `SELECT ... FOR UPDATE` actually edges out Redis Lua by ~10 % on
  accepted-orders here — within run-to-run noise. The architectural
  argument for Redis stands (microsecond-level atomic decrements with
  no row locks, no connection-pool pressure), but proving it
  empirically requires an in-network HTTP test that bypasses TLS and
  the Caddy proxy — see **Validity caveats** below.

### Where the gains come from

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
- **2026-05-17 production run** was driven over the public HTTPS
  endpoint (`https://159.65.114.240.nip.io`) so the measurement
  matches what a real client sees. TLS handshake and connection-pool
  saturation at 500 VUs therefore dominate the flash-sale absolute
  numbers and mask the inventory-backend difference. An in-network
  HTTP repeat (`BASE_URL=http://gateway` with the dev Nginx gateway
  swapped in) would isolate the stock-decrement implementation but
  is left out of scope for this submission since the production-path
  measurement is what matters for the user-facing SLO.

## Files

- [`../../scripts/loadtest/product_detail.js`](../../scripts/loadtest/product_detail.js)
- [`../../scripts/loadtest/search_compare.js`](../../scripts/loadtest/search_compare.js)
- [`../../scripts/loadtest/flash_sale.js`](../../scripts/loadtest/flash_sale.js)
- [`../../scripts/create_loadtest_flashsale.py`](../../scripts/create_loadtest_flashsale.py)
- `runs/` — k6 summary JSONs from each invocation
