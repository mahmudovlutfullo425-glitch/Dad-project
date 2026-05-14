.PHONY: help up down restart logs ps clean config \
        build-api db-up db-migrate seed db-reset db-shell reindex

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

up:
	docker compose --env-file .env up -d

down:
	docker compose --env-file .env down

restart:
	docker compose --env-file .env restart

logs:
	docker compose --env-file .env logs -f --tail=100

ps:
	docker compose --env-file .env ps

config:
	docker compose --env-file .env config

clean:
	docker compose --env-file .env down -v

build-api:
	docker compose --env-file .env build api

db-up:
	docker compose --env-file .env up -d db
	@echo "Waiting for db to be healthy..."
	@until docker compose exec -T db pg_isready -U $${POSTGRES_USER:-ecom} >/dev/null 2>&1; do sleep 1; done
	@echo "db is ready."

db-migrate: build-api db-up
	docker compose --env-file .env run --rm api alembic upgrade head

seed: db-migrate
	docker compose --env-file .env run --rm \
		-v "$(CURDIR)/scripts:/scripts" \
		-w /app -e PYTHONPATH=/app \
		api python /scripts/seed.py

db-reset:
	docker compose --env-file .env down db
	docker volume rm ecommerce-flashsale_pg_data 2>/dev/null || true
	$(MAKE) seed

db-shell:
	docker compose --env-file .env exec db psql -U $${POSTGRES_USER:-ecom} -d $${POSTGRES_DB:-ecommerce}

reindex:
	docker compose --env-file .env run --rm \
		-v "$(CURDIR)/scripts:/scripts" \
		-w /app -e PYTHONPATH=/app \
		api python /scripts/reindex_products.py
