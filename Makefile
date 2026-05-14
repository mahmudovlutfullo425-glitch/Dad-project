.PHONY: help up down restart logs ps clean db-up db-reset seed config

help:
	@echo "Available targets:"
	@echo "  make up        - Bring up the full stack"
	@echo "  make down      - Stop the stack"
	@echo "  make restart   - Restart the stack"
	@echo "  make logs      - Tail logs from all services"
	@echo "  make ps        - Show running services"
	@echo "  make config    - Validate docker-compose configuration"
	@echo "  make clean     - Stop stack and remove all volumes (destructive)"
	@echo "  make db-up     - Bring up DB and apply migrations"
	@echo "  make db-reset  - Drop and recreate DB from scratch with seed"

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

db-up:
	docker compose --env-file .env up -d db
	@echo "Run 'make seed' after migrations are added in Step 2"

db-reset:
	docker compose --env-file .env down db
	docker volume rm ecommerce-flashsale_pg_data || true
	docker compose --env-file .env up -d db

seed:
	@echo "Seed target will be implemented in Step 2"
