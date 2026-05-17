# Changelog

All notable changes to this project. Format inspired by
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions
follow the 19-step build plan in `PROJECT.md`.

## [1.0.0] — 2026-05-17

First public release: full 19-step build plan executed, R6
measurements captured against the production droplet, design report
+ ER diagram + architecture diagram + 7 ADRs + 5 BPMN workflows all
in repo. Live deployment at `https://159.65.114.240.nip.io/`.

### Added — Step 1 (Platform skeleton)
- Docker Compose stack with 16 services on `ecom-net` bridge.
- `.env.example` template covering every required variable.
- `Makefile` operational targets (`up`, `down`, `seed`, `reindex`,
  `k6-all`, etc.).

### Added — Step 2 (Postgres schema)
- 14 SQLAlchemy 2.0 ORM models with FK constraints, check
  constraints, JSONB columns, and 3 enum types.
- Alembic migrations `0001_initial_schema` and
  `0002_add_order_reservation_id`.
- `scripts/seed.py` — deterministic Faker seed: 50 categories, 1000
  products, ~2000 variants, 10 users, 1 upcoming flash sale.

### Added — Step 3 (REST API core)
- FastAPI app with OpenAPI tags, CORS, lifespan hooks.
- JWT auth with bcrypt password hashing.
- `/auth/{register,login,me}` and `/products{,/<id>,/<id>/variants}`
  endpoints with full admin CRUD.

### Added — Step 4 (Gateway + load balancing)
- Nginx gateway with `least_conn` upstream balancing 2 api replicas.
- DNS-based per-request resolution so traffic spreads across both
  replicas instead of pinning to the first.
- Routes for `/api/*`, `/docs`, `/redoc`, `/openapi.json`.

### Added — Step 5 (Redis cart)
- Async Redis client wrapper with TTL extension on every cart
  operation.
- Cart endpoints (GET / POST item / PATCH item / DELETE item / DELETE).
- Cart hash keyed by `cart:{user_id}` with 7-day TTL.

### Added — Step 6 (Meilisearch)
- Async Meilisearch client with facets for `category_name`, `brand`,
  `in_stock`.
- `GET /search/products` with typo tolerance + filters + sort.
- `scripts/reindex_products.py` for full Postgres → Meilisearch sync.

### Added — Step 7 (Inventory gRPC service)
- `inventory.proto` with four RPCs: `CheckStock`, `ReserveStock`,
  `CommitReservation`, `ReleaseReservation`.
- Inventory bootstrap that loads `inventory_levels` → Redis on
  service start (with a startup lock to prevent two-replica race).
- gRPC reflection enabled for `grpcurl` introspection during viva.

### Added — Step 8 (R11 — token-bucket rate limiter)
- Pure-Python `TokenBucket` dataclass + Redis-backed shared state.
- Lua script for atomic refill-and-consume.
- FastAPI middleware **and** gRPC interceptor sharing the same
  algorithm.
- Four named rules (`FLASH_BUY_PER_USER`, `LOGIN_PER_IP`,
  `CHECKOUT_GLOBAL`, `API_PER_USER_DEFAULT`).
- Prometheus counters `rate_limit_allowed_total` and
  `rate_limit_rejected_total` per rule.
- Pytest tests for bucket math, refill behaviour, clock skew.

### Added — Step 9 (Checkout + orders + flash-sale buy)
- `POST /checkout` — reads Redis cart → `ReserveStock` via gRPC →
  creates Order/Payment → enqueues Celery chain → clears cart.
- `GET /orders` and `GET /orders/{id}` with admin override.
- `POST /flashsales/{id}/buy` — fast path with per-user purchase cap
  (Redis INCR + cap check) and ClickHouse event emit.

### Added — Step 10 (Celery pipeline + BPMN)
- 5-task chain: `capture_payment → commit_inventory →
  generate_invoice → notify_customer → schedule_dispatch`.
- Beat-scheduled jobs: hourly cart expiry, daily settlement, low-stock
  alerts, every-5-min flash-sale post-mortem.
- 5 BPMN 2.0 workflow diagrams in `docs/bpmn/`.

### Added — Step 11 (ClickHouse analytics)
- `analytics.flash_sale_events`, `analytics.order_events` MergeTree
  tables with 90-day TTL.
- Materialised view `flash_sale_minute_stats` aggregating events to
  per-minute buckets.
- `app/clickhouse_client.py` async + sync clients with emit helpers.
- Admin analytics endpoints: per-flash-sale rollup, daily orders.

### Added — Step 12 (Observability)
- OpenTelemetry Collector ingesting OTLP traces + logs + metrics
  from all services.
- Tempo (traces, 24 h retention), Loki (logs, 24 h), Prometheus
  (metrics, 24 h), Grafana with pre-provisioned datasources and the
  "Flash-Sale Operations" dashboard.
- Auto-instrumentation for FastAPI, SQLAlchemy, gRPC, Celery, Redis,
  httpx — trace context propagates across the api → inventory hop.

### Added — Step 13 (R6 measurements)
- Three k6 load-test scripts in `scripts/loadtest/` driving 100–500 VUs.
- Env-flag-driven implementation swap (`PRODUCT_CACHE_ENABLED`,
  `USE_POSTGRES_STOCK`, `RATE_LIMIT_ENABLED`) so the same codebase
  measures both baseline and optimised paths.
- Make targets for each scenario plus `make k6-all` for the full sweep.
- Results recorded in `docs/measurements/README.md`:
  - Product detail: **4.3× lower p50**, **4× higher RPS** with hot cache.
  - Search: **2.7× lower p50** with Meilisearch vs Postgres ILIKE.
  - Flash-sale decrement: approximately tied at 500 VUs over public TLS
    (bottleneck shifts to TLS handshake — caveat documented).

### Added — Step 14 (BPMN diagrams)
- 5 BPMN 2.0 XML files + PNG exports for the report:
  `order-fulfilment.bpmn`, `flashsale-buy.bpmn`,
  `expire-stuck-orders.bpmn`, `daily-settlement.bpmn`,
  `flashsale-postmortem.bpmn`.

### Added — Step 15 (Next.js frontend)
- Next.js 14 storefront with App Router, Tailwind, Server Components.
- Pages: home, catalogue, product detail, search, cart, checkout,
  orders, flash sale.
- Admin shell: orders table, inventory table, analytics dashboard.
- Auth pages: register, login, account.

### Added — Step 16 (Deployment)
- `scripts/deploy/install.sh` — Ubuntu 24.04 bootstrap (Docker +
  Compose + UFW + kernel limits).
- `gateway/Caddyfile` — auto-TLS reverse proxy with Let's Encrypt.
- `gateway-prod` compose profile and `make up-prod` Make target.
- `scripts/deploy/README.md` — full walkthrough from droplet
  creation to verified HTTPS in ~25 minutes.
- Deployed to DigitalOcean droplet at `https://159.65.114.240.nip.io/`.

### Added — Step 17 (Documentation)
- 7 ADRs in `docs/adr/` for the non-obvious decisions.
- Hand-drawn ER diagram in `docs/diagrams/er-diagram.png`.
- Architecture diagram in `docs/diagrams/architecture.png` (plus
  Mermaid source for in-repo rendering).
- This `CHANGELOG.md`.

### Added — Step 18 (Design report)
- 10–15 page PDF report covering R1 (use cases), R2 (architecture
  + ER), R5 (polyglot), R6 (measurements), R10 (pipeline + BPMN),
  R11 (rate limiter), R12 (observability).
