# Flash-Sale E-commerce Platform

A distributed e-commerce system with real-time inventory management, flash-sale capabilities, and full observability. Built for the Database Application and Design course (Spring 2026) at Inha University in Tashkent.

## Quick start

```bash
git clone <repo-url>
cd ecommerce-flashsale
cp .env.example .env
make up
```

The application will be available at `http://localhost` once all services report healthy.

## Architecture

The system follows a microservices architecture with the following components:

- **Gateway** — Nginx reverse proxy with TLS termination and load balancing
- **API service** — FastAPI application (×2 replicas) serving REST endpoints
- **Inventory service** — Dedicated gRPC service for stock operations
- **Worker** — Celery worker executing the order-fulfilment pipeline
- **Beat** — Celery scheduler for batch jobs
- **Frontend** — Next.js storefront and admin panel
- **PostgreSQL** — Primary relational store
- **Redis** — Cache, session store, and atomic stock counters
- **Meilisearch** — Product search engine
- **ClickHouse** — Analytics and event store
- **NATS** — Event stream backbone
- **OpenTelemetry stack** — Tempo (traces), Loki (logs), Prometheus (metrics), Grafana

A full architecture diagram is available in `docs/diagrams/architecture.png`.

## Environment variables

See `.env.example` for the full list. Copy it to `.env` and adjust values as needed.

## Project structure

```
api/             FastAPI backend (REST + Celery tasks)
inventory/       Inventory microservice (gRPC server)
frontend/       Next.js storefront and admin panel
migrations/      Alembic migration scripts
gateway/         Nginx configuration
observability/   OpenTelemetry, Grafana, Tempo, Loki, Prometheus configs
docs/            ADRs, BPMN diagrams, ER diagram, architecture diagrams
scripts/         Operational scripts (load tests, seed, etc.)
```

## Useful commands

| Command | Description |
|---|---|
| `make up` | Start the full stack |
| `make down` | Stop the stack |
| `make logs` | Tail logs |
| `make ps` | Show running services |
| `make db-reset` | Drop and recreate the database |
| `make config` | Validate the docker-compose configuration |

## Documentation

- API documentation (live): `http://localhost/api/docs`
- Architecture overview: `docs/diagrams/architecture.png`
- ER diagram: `docs/diagrams/er-diagram.png`
- BPMN workflows: `docs/bpmn/`
- Architecture decisions: `docs/adr/`

## License

This project is submitted as coursework. All rights reserved by the team.
