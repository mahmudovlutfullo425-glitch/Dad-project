.PHONY: help up down restart logs ps clean config \
        build-api db-up db-migrate seed db-reset db-shell reindex \
        loadtest-flashsale \
        k6-product-detail-baseline k6-product-detail-cached \
        k6-search-compare \
        k6-flash-sale-redis k6-flash-sale-postgres \
        k6-all \
        frontend-build frontend-logs frontend-dev

# ---- internal helpers (not in .PHONY) ----
COMPOSE := docker compose --env-file .env
K6_NETWORK := ecommerce-flashsale_ecom-net
K6_IMAGE := grafana/k6:0.54.0
K6_OUTPUT_DIR := docs/measurements/runs
K6_RUN_DOCKER = docker run --rm -i \
        --network=$(K6_NETWORK) \
        -v "$(CURDIR)/scripts/loadtest:/scripts:ro" \
        -v "$(CURDIR)/$(K6_OUTPUT_DIR):/output" \
        -e BASE_URL=http://gateway \
        $(K6_IMAGE) run

help:
	@echo "Available targets:"
	@echo ""
	@echo "  Stack:"
	@echo "    make up         - Bring up the full stack"
	@echo "    make down       - Stop the stack"
	@echo "    make restart    - Restart the stack"
	@echo "    make logs       - Tail logs from all services"
	@echo "    make ps         - Show running services"
	@echo "    make config     - Validate docker-compose configuration"
	@echo "    make clean      - Stop stack and remove all volumes (destructive)"
	@echo ""
	@echo "  Database:"
	@echo "    make build-api  - Build the api image"
	@echo "    make db-up      - Bring up the database (and wait for healthy)"
	@echo "    make db-migrate - Apply Alembic migrations to head"
	@echo "    make seed       - Migrate and load deterministic seed data"
	@echo "    make db-reset   - Wipe the database volume and rebuild from seed"
	@echo "    make db-shell   - Open a psql shell in the db container"
	@echo ""
	@echo "  Search:"
	@echo "    make reindex    - Rebuild the Meilisearch products index from Postgres"
	@echo ""
	@echo "  Load tests (R6 measurements — results land in $(K6_OUTPUT_DIR)/):"
	@echo "    make loadtest-flashsale          - Create / refresh the active flash sale used by k6-flash-sale-*"
	@echo "    make k6-product-detail-baseline  - Product /products/{id} with cache OFF"
	@echo "    make k6-product-detail-cached    - Product /products/{id} with cache ON (default)"
	@echo "    make k6-search-compare           - Postgres ILIKE vs Meilisearch, sequential"
	@echo "    make k6-flash-sale-redis         - Flash-sale buy with Redis Lua DECRBY (default)"
	@echo "    make k6-flash-sale-postgres      - Flash-sale buy with Postgres SELECT FOR UPDATE"
	@echo "    make k6-all                      - Run every measurement back-to-back"
	@echo ""
	@echo "  Frontend (Next.js storefront + admin):"
	@echo "    make frontend-build              - Build the frontend Docker image"
	@echo "    make frontend-logs               - Tail frontend logs"
	@echo "    make frontend-dev                - Local Next.js dev server (npm install + dev)"

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

config:
	$(COMPOSE) config

clean:
	$(COMPOSE) down -v

build-api:
	$(COMPOSE) build api

db-up:
	@echo "Bringing up db and waiting for healthcheck..."
	$(COMPOSE) up -d --wait db

db-migrate: build-api db-up
	$(COMPOSE) run --rm api alembic upgrade head

seed: db-migrate
	$(COMPOSE) run --rm \
		-v "$(CURDIR)/scripts:/scripts" \
		-w /app -e PYTHONPATH=/app \
		api python /scripts/seed.py

db-reset:
	$(COMPOSE) down db
	-docker volume rm ecommerce-flashsale_pg_data
	$(MAKE) seed

db-shell:
	$(COMPOSE) exec db psql -U ecom -d ecommerce

reindex:
	$(COMPOSE) run --rm \
		-v "$(CURDIR)/scripts:/scripts" \
		-w /app -e PYTHONPATH=/app \
		api python /scripts/reindex_products.py

# ============================================================
# R6 — load tests (Step 13)
# ============================================================
# Each k6 target writes a JSON summary to $(K6_OUTPUT_DIR)/<scenario>_<mode>_<ts>.json.
# Shell env vars override the .env defaults at compose-parse time so
# api / inventory come up with the feature flag the run requires.
# The restore step at the end of each baseline target brings the
# services back to production defaults so subsequent runs are clean.

loadtest-flashsale:
	$(COMPOSE) run --rm \
		-v "$(CURDIR)/scripts:/scripts" \
		-w /app -e PYTHONPATH=/app \
		api python /scripts/create_loadtest_flashsale.py
	@echo ">>> Restarting inventory to refresh stock counters in Redis..."
	$(COMPOSE) restart inventory
	@echo ">>> Done. Inventory will be ready in ~10s."

# Each k6 target writes a fixed-name summary into $(K6_OUTPUT_DIR)/. Re-running
# the same target overwrites its previous summary — copy / rename manually if
# you want to keep history. Fixed names instead of timestamps + env-file
# overrides instead of `VAR=value cmd` keep the targets portable across
# cmd / PowerShell / Git Bash.

# Compose invocations with extra layered env files (scripts/loadtest/env.*).
# Compose merges --env-file values in order; later files win on conflicts.
COMPOSE_CACHE_OFF  := $(COMPOSE) --env-file scripts/loadtest/env.cache-off
COMPOSE_NORATE     := $(COMPOSE) --env-file scripts/loadtest/env.no-ratelimit
COMPOSE_NORATE_PG  := $(COMPOSE) --env-file scripts/loadtest/env.no-ratelimit \
                                 --env-file scripts/loadtest/env.pg-stock

k6-product-detail-baseline:
	@echo ">>> Recreating api with PRODUCT_CACHE_ENABLED=false..."
	$(COMPOSE_CACHE_OFF) up -d --force-recreate --no-deps --wait api
	$(K6_RUN_DOCKER) \
		--summary-export=/output/product_detail_baseline.json \
		--tag mode=baseline \
		/scripts/product_detail.js
	@echo ">>> Restoring api to default config..."
	$(COMPOSE) up -d --force-recreate --no-deps --wait api

k6-product-detail-cached:
	@echo ">>> Ensuring api is on default config (cache ON)..."
	$(COMPOSE) up -d --force-recreate --no-deps --wait api
	$(K6_RUN_DOCKER) \
		--summary-export=/output/product_detail_cached.json \
		--tag mode=cached \
		/scripts/product_detail.js

k6-search-compare:
	$(K6_RUN_DOCKER) \
		--summary-export=/output/search_compare.json \
		/scripts/search_compare.js

k6-flash-sale-redis: loadtest-flashsale
	@echo ">>> Recreating api + inventory with RATE_LIMIT_ENABLED=false, USE_POSTGRES_STOCK=false..."
	$(COMPOSE_NORATE) up -d --force-recreate --no-deps --wait api inventory
	$(K6_RUN_DOCKER) \
		--summary-export=/output/flash_sale_redis.json \
		--tag mode=redis_lua \
		/scripts/flash_sale.js
	@echo ">>> Restoring api + inventory to default config..."
	$(COMPOSE) up -d --force-recreate --no-deps --wait api inventory

k6-flash-sale-postgres: loadtest-flashsale
	@echo ">>> Recreating api + inventory with RATE_LIMIT_ENABLED=false, USE_POSTGRES_STOCK=true..."
	$(COMPOSE_NORATE_PG) up -d --force-recreate --no-deps --wait api inventory
	$(K6_RUN_DOCKER) \
		--summary-export=/output/flash_sale_postgres.json \
		--tag mode=postgres_lock \
		/scripts/flash_sale.js
	@echo ">>> Restoring api + inventory to default config..."
	$(COMPOSE) up -d --force-recreate --no-deps --wait api inventory

k6-all: k6-product-detail-baseline k6-product-detail-cached k6-search-compare \
        k6-flash-sale-postgres k6-flash-sale-redis
	@echo ""
	@echo "All R6 measurements complete. Summaries in $(K6_OUTPUT_DIR)/."

# ============================================================
# Frontend (Step 15)
# ============================================================

frontend-build:
	$(COMPOSE) build frontend

frontend-logs:
	$(COMPOSE) logs -f --tail=100 frontend

# Local hot-reload dev server. Points at the gateway so the api / Meili
# / inventory still come from the compose stack — only the Next.js
# layer runs natively. Requires node 20+.
frontend-dev:
	cd frontend && npm install && NEXT_PUBLIC_API_URL=http://localhost/api INTERNAL_API_URL=http://localhost/api npm run dev
