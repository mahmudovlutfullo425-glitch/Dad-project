# Flash-Sale E-commerce Platform

A distributed e-commerce system with real-time inventory, a custom Redis-backed
rate limiter, polyglot persistence (Postgres + Redis + Meilisearch + ClickHouse),
gRPC inter-service comms, async order pipeline (Celery), and an
OpenTelemetry/Grafana observability stack.

Built for the **Database Application and Design** course (Spring 2026),
Inha University in Tashkent.

---

## Table of contents

1. [Prerequisites](#prerequisites)
2. [Quick start (TL;DR)](#quick-start-tldr)
3. [Detailed setup — step by step](#detailed-setup--step-by-step)
4. [Services & ports](#services--ports)
5. [What gets created on first boot](#what-gets-created-on-first-boot)
6. [Verifying the stack](#verifying-the-stack)
7. [Common operations](#common-operations)
8. [Project structure](#project-structure)
9. [Endpoints overview](#endpoints-overview)
10. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- **Docker** 24+ and **Docker Compose v2** (`docker compose ...`, not the
  legacy `docker-compose`). Docker Desktop 4.20+ on Windows/macOS works.
- **GNU Make** (preinstalled on macOS/Linux; on Windows use Git Bash, WSL, or
  install via `choco install make`).
- **Git**.
- ~6 GB of free disk for Docker volumes (Postgres, Redis, Meilisearch,
  ClickHouse, Grafana).
- Ports `80`, `443` free on the host (the Nginx gateway binds them). Internal
  service ports stay inside the `ecom-net` bridge network and never touch the
  host.

---

## Quick start (TL;DR)

```bash
git clone <repo-url>
cd ecommerce-flashsale
cp .env.example .env       # tweak secrets for prod; defaults are dev-safe
make up                    # boot every container (15 services)
make seed                  # apply Alembic migrations + load fixtures
make reindex               # push products into Meilisearch
```

Then open:

- **Storefront** — http://localhost
- **Swagger UI** — http://localhost/docs
- **OpenAPI JSON** — http://localhost/openapi.json
- **API health** — http://localhost/api/health

Default admin (created by `make seed`): `admin@ecom.local` / `admin123`.
Test users: `user1@ecom.local` … `user9@ecom.local` / `user1234`.

---

## Detailed setup — step by step

If you'd rather see each phase explicitly:

### 1. Clone & configure

```bash
git clone <repo-url>
cd ecommerce-flashsale
cp .env.example .env
```

The `.env` file holds DB credentials, JWT secret, service hosts, ClickHouse
auth, and CORS settings. The defaults are dev-safe (everything talks to
sibling containers on `ecom-net`). For deployment, rotate `JWT_SECRET`,
`POSTGRES_PASSWORD`, `MEILI_MASTER_KEY`, and `CLICKHOUSE_PASSWORD`.

### 2. Build & start the stack

```bash
make up
```

This does `docker compose --env-file .env up -d` and brings up all 16 services
in dependency order:

```
db, redis, meilisearch, clickhouse, nats   (data tier)
  → inventory  (gRPC; depends on db + redis healthy)
  → api ×2     (depends on db, redis, meili, clickhouse healthy)
  → worker, beat  (Celery; depends on redis, db, inventory healthy)
  → gateway    (Nginx; depends on api)
  → frontend
  → otel-collector, tempo, loki, prometheus, grafana
```

Healthchecks gate dependent containers — you'll see `(healthy)` in
`docker compose ps` when a service is fully ready.

> **First boot only** — ClickHouse runs [`scripts/clickhouse_init.sql`](scripts/clickhouse_init.sql)
> via its standard `/docker-entrypoint-initdb.d` mechanism. This creates the
> `analytics` database with `flash_sale_events`, `order_events`, and the
> `flash_sale_minute_stats` materialised view. The script is idempotent
> (`CREATE … IF NOT EXISTS`) but only auto-runs when the `ch_data` volume
> is empty. To force a re-run on an existing volume:
>
> ```bash
> docker compose exec clickhouse clickhouse-client \
>   --user $CLICKHOUSE_USER --password $CLICKHOUSE_PASSWORD \
>   < scripts/clickhouse_init.sql
> ```

### 3. Apply migrations & seed Postgres

```bash
make seed
```

What this does, in order:

1. `make build-api` — builds the `api` Docker image (compiles
   `inventory.proto`, installs Python deps).
2. `make db-up` — starts Postgres and waits for it to be healthy.
3. `alembic upgrade head` — runs migrations `0001_initial_schema` (14 tables)
   then `0002_add_order_reservation_id` (Celery hand-off column).
4. Runs `scripts/seed.py` inside an ephemeral `api` container:
   - 50 categories, 1000 products, ~2000 variants, ~10 users with addresses.
   - One upcoming flash sale (starts in ~1 hour, ends in ~3 hours) with
     20 items at 40% discount.
   - Random stock 0–500 per variant, deterministic via Faker seed `42`.

Re-running `make seed` is **idempotent** — it skips rows that already exist by
their unique keys.

### 4. Push products into Meilisearch

```bash
make reindex
```

Runs `scripts/reindex_products.py`: pulls all active products + variants from
Postgres and bulk-inserts ~1000 documents into the `products` index. After
this, `GET /api/search/products?q=…` returns hits in < 20 ms with facets
for `brand`, `category_name`, and `in_stock`.

Subsequent product create/update calls index inline; only a full re-sync
needs this command.

### 5. Inventory bootstrap (automatic)

When the `inventory` container starts, it reads every row in `inventory_levels`
and writes `stock:{variant_id}` keys into Redis with the available count.
A startup lock in Redis prevents the two-replica race. **No manual step
required** — but if you reset Postgres, restart the `inventory` container so
it re-bootstraps:

```bash
docker compose restart inventory
```

### 6. Verify

See [Verifying the stack](#verifying-the-stack) below.

---

## Services & ports

| Service | Image | Internal port | Exposed | Health |
|---|---|---|---|---|
| `gateway` | nginx:1.27-alpine | 80 | **80, 443** | `wget /gw-health` |
| `api` ×2 | built from `./api` | 8000 | — | `GET /health` |
| `inventory` | built from `./inventory` | 50051 | — | TCP socket open |
| `worker` | built from `./api` | — (Celery) | — | — |
| `beat` | built from `./api` | — (Celery beat) | — | — |
| `frontend` | built from `./frontend` | 3000 | — | — |
| `db` | postgres:16-alpine | 5432 | — | `pg_isready` |
| `redis` | redis:7-alpine | 6379 | — | `redis-cli ping` |
| `meilisearch` | getmeili/meilisearch:v1.10 | 7700 | — | `GET /health` |
| `clickhouse` | clickhouse-server:24.8-alpine | 8123 (HTTP), 9000 (TCP) | — | `GET /ping` |
| `nats` | nats:2.10-alpine | 4222 | — | `GET /healthz` |
| `otel-collector` | otel-collector-contrib:0.110.0 | 4317 (gRPC) | — | — |
| `tempo` | grafana/tempo:2.6.0 | 3200 | — | — |
| `loki` | grafana/loki:3.2.0 | 3100 | — | — |
| `prometheus` | prom/prometheus:v2.55.0 | 9090 | — | — |
| `grafana` | grafana/grafana:11.3.0 | 3000 | — | — |

All inter-service traffic stays on the private `ecom-net` bridge. Public
ingress is only via the gateway.

---

## What gets created on first boot

| Resource | Owner | Trigger |
|---|---|---|
| `pg_data` volume + 14 tables + 2 enum types | Alembic via `make seed` | first `make seed` |
| Seed data (1000 products, flash sale, etc.) | `scripts/seed.py` | `make seed` |
| `redis_data` volume + cart/stock/bucket keys | Redis AOF | lazy |
| `stock:{variant_id}` counters | inventory bootstrap | inventory container start |
| `meili_data` volume + `products` index | Meilisearch + `make reindex` | `make reindex` |
| `ch_data` volume + `analytics` DB + 2 tables + MV | `clickhouse_init.sql` bind-mount | first clickhouse start |
| `grafana_data` volume + datasources | Grafana provisioning | first grafana start |

---

## Verifying the stack

After `make up && make seed && make reindex`:

```bash
# 1. All containers healthy?
make ps

# 2. API liveness
curl http://localhost/api/health
# → {"status":"ok"}

# 3. Swagger UI
open http://localhost/docs

# 4. Catalogue
curl 'http://localhost/api/products?page=1&page_size=3'

# 5. Search hits Meilisearch
curl 'http://localhost/api/search/products?q=acme&limit=3'

# 6. Auth round-trip
TOKEN=$(curl -s -X POST http://localhost/api/auth/login \
  -d 'username=user1@ecom.local&password=user1234' | jq -r .access_token)
curl -H "Authorization: Bearer $TOKEN" http://localhost/api/auth/me

# 7. Cart (Redis-backed)
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"variant_id":1,"quantity":2}' \
  http://localhost/api/cart/items

# 8. Inventory & rate-limiter end-to-end smoke tests
python scripts/inventory_check.py
python scripts/ratelimit_grpc_check.py

# 9. ClickHouse — analytics tables exist
docker compose exec clickhouse clickhouse-client \
  --user $CLICKHOUSE_USER --password $CLICKHOUSE_PASSWORD \
  -q "SHOW TABLES FROM analytics"

# 10. Celery worker is consuming
docker compose logs --tail=20 worker
```

After placing an order via Swagger or curl, you should see the 5-task chain
run in the worker log:

```
capture_payment → commit_inventory → generate_invoice → notify_customer → schedule_dispatch
```

---

## Common operations

### Daily

```bash
make up                # start the stack
make down              # stop (keeps volumes)
make restart           # restart everything
make logs              # tail all service logs
make ps                # show service state + health
```

### Database

```bash
make db-up             # only start postgres (no api/worker)
make db-migrate        # alembic upgrade head (rebuilds api image first)
make seed              # migrate + load seed data (idempotent)
make db-shell          # psql into the running db container
make db-reset          # destroy pg volume and rebuild from seed (DESTRUCTIVE)
```

### Search

```bash
make reindex           # rebuild the Meilisearch `products` index from Postgres
```

### Inspect the data tier directly

```bash
# Postgres
docker compose exec db psql -U $POSTGRES_USER -d $POSTGRES_DB
# > \dt              -- list tables
# > SELECT count(*) FROM products;

# Redis
docker compose exec redis redis-cli
# > KEYS stock:*
# > GET stock:1
# > HGETALL cart:2

# Meilisearch
curl -H "Authorization: Bearer $MEILI_MASTER_KEY" \
  http://localhost:7700/indexes/products/stats   # only inside ecom-net by default

# ClickHouse
docker compose exec clickhouse clickhouse-client \
  --user $CLICKHOUSE_USER --password $CLICKHOUSE_PASSWORD
# > USE analytics;
# > SELECT action, count() FROM flash_sale_events GROUP BY action;
```

### Tear down

```bash
make down              # stop containers, keep volumes
make clean             # stop + remove ALL volumes (destructive)
```

---

## Project structure

```
api/                        FastAPI backend + Celery tasks
├── app/
│   ├── main.py             FastAPI app + lifespan + router wiring
│   ├── config.py           Pydantic settings (env → Settings)
│   ├── db.py               Async SQLAlchemy engine (asyncpg)
│   ├── db_sync.py          Sync engine for Celery tasks (psycopg2)
│   ├── models.py           14 ORM models
│   ├── deps.py             FastAPI dependencies (auth, admin)
│   ├── security.py         JWT + bcrypt
│   ├── redis_client.py     Async Redis (cart + counters)
│   ├── search_client.py    Async Meilisearch wrapper
│   ├── grpc_client.py      Async gRPC stub for inventory (FastAPI routes)
│   ├── grpc_client_sync.py Sync stub (Celery tasks)
│   ├── clickhouse_client.py Async + sync ClickHouse clients + emit helpers
│   ├── worker.py           Celery app + beat schedule
│   ├── ratelimit/          Token-bucket limiter (R11) — shared with inventory
│   ├── routers/            REST endpoints (auth, products, cart, search,
│   │                       checkout, orders, flashsales, admin_analytics)
│   ├── schemas/            Pydantic request/response models
│   └── tasks/
│       ├── order.py        5-task fulfilment chain
│       └── scheduled.py    Beat jobs (stuck orders, postmortem, etc.)
├── migrations/             Alembic
├── proto/                  inventory.proto (mirror of inventory/proto/)
├── Dockerfile
└── requirements.txt

inventory/                  Inventory gRPC microservice
├── app/
│   ├── server.py           asyncio gRPC server
│   ├── service.py          Servicer (CheckStock / Reserve / Commit / Release)
│   ├── lua_scripts.py      Atomic reserve script
│   ├── ratelimit/          Token-bucket limiter + tests
│   ├── redis_client.py
│   ├── db.py
│   └── config.py
├── proto/inventory.proto
└── Dockerfile

gateway/                    Nginx config (2-replica LB, /api → api, / → frontend)
frontend/                   Next.js storefront (Step 15)
observability/              OTel + Grafana + Tempo + Loki + Prometheus configs (Step 12)
scripts/
├── seed.py                 Deterministic data loader
├── reindex_products.py     Postgres → Meilisearch bulk index
├── clickhouse_init.sql     Bind-mounted to clickhouse:/docker-entrypoint-initdb.d/
├── inventory_check.py      gRPC happy-path smoke test
└── ratelimit_grpc_check.py 429-from-inventory smoke test
docs/
├── adr/                    Architecture decision records
├── bpmn/                   5 workflow diagrams (Step 14)
└── diagrams/               ER + architecture diagrams
docker-compose.yml          All 16 services
Makefile                    Operational targets
.env.example                Env-var reference
```

---

## Endpoints overview

Live Swagger: **http://localhost/docs**

| Path | Auth | Purpose |
|---|---|---|
| `POST /api/auth/register` | — | Create user |
| `POST /api/auth/login` | — | Form login → JWT |
| `GET /api/auth/me` | Bearer | Current user |
| `GET /api/products` | — | Browse catalogue with filters |
| `GET /api/products/{id}` | — | Detail |
| `POST/PATCH/DELETE /api/products{/id}` | Admin | CRUD |
| `GET /api/categories` | — | List categories |
| `GET /api/search/products` | — | Meilisearch (typo-tolerant + facets) |
| `GET /api/cart` | Bearer | Redis-backed live cart |
| `POST /api/cart/items` | Bearer | Add / increment |
| `PATCH /api/cart/items/{vid}` | Bearer | Set quantity |
| `DELETE /api/cart/items/{vid}` | Bearer | Remove |
| `POST /api/checkout` | Bearer | Place order from cart |
| `GET /api/orders` | Bearer | Own order history |
| `GET /api/orders/{id}` | Bearer / Admin | Detail |
| `GET /api/flashsales` | — | Active / upcoming sales |
| `GET /api/flashsales/{id}` | — | Detail |
| `POST /api/flashsales/{id}/buy` | Bearer | Rate-limited fast-buy |
| `GET /api/admin/analytics/flashsales/{id}` | Admin | ClickHouse rollup |
| `GET /api/admin/analytics/orders/daily?days=N` | Admin | Daily revenue/status |
| `GET /api/health` | — | Liveness |

---

## Troubleshooting

### `make up` fails — port already in use
Something else is on port 80. Edit `.env`:
```
GATEWAY_HTTP_PORT=8080
```
Then `make restart`. The storefront is now at http://localhost:8080.

### `make seed` errors — `relation "users" does not exist`
The migration didn't run. Try:
```bash
docker compose --env-file .env run --rm api alembic upgrade head
make seed
```

### Order placed but worker doesn't process it
```bash
docker compose logs worker --tail=50
docker compose logs beat --tail=20
```
If you see "Connection refused" against Redis, the broker isn't healthy. Run
`make ps` and look for `redis (healthy)`.

### ClickHouse: `Table flash_sale_events doesn't exist`
The init script only runs on first boot. Re-apply manually:
```bash
docker compose exec -T clickhouse clickhouse-client \
  --user $CLICKHOUSE_USER --password $CLICKHOUSE_PASSWORD \
  --multiquery < scripts/clickhouse_init.sql
```
Or destroy the volume and re-init:
```bash
docker compose down clickhouse
docker volume rm ecommerce-flashsale_ch_data
docker compose up -d clickhouse
```

### Meilisearch returns zero hits
You haven't reindexed since seeding:
```bash
make reindex
```

### Inventory service shows zero stock for everything
The bootstrap step (Postgres → Redis) ran before seed finished, so Redis
counters are all zero. Reseed and restart the inventory:
```bash
make seed
docker compose restart inventory
```

### Reset everything
```bash
make clean   # destroys ALL volumes — pg, redis, meili, clickhouse, grafana
make up
make seed
make reindex
```

---

## Documentation

- Live API docs: http://localhost/docs
- Architecture diagram: `docs/diagrams/architecture.png`
- ER diagram (hand-drawn): `docs/diagrams/er-diagram.png`
- BPMN workflows: `docs/bpmn/`
- Architecture decisions: `docs/adr/`
- Measurement notes (R6): `docs/measurements/`

---

## License

Submitted as coursework. All rights reserved by the team.
