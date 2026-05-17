# Architecture Decision Records

Lightweight write-ups of the non-obvious architectural choices made on
this project. Each ADR follows the
[Michael Nygard format](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions):
**Context → Decision → Consequences → Alternatives**.

The point of writing these down is so the team (and the grader) can
defend each decision in the viva — "we chose X because Y, considered
Z, accepted the trade-off W."

| # | Title | Owner | Date |
|---|---|---|---|
| [0001](0001-polyglot-persistence.md) | Polyglot persistence: Postgres + Redis + Meilisearch + ClickHouse | M3 | 2026-02-15 |
| [0002](0002-token-bucket-rate-limiter.md) | Token-bucket rate limiter from scratch (R11 from-scratch component) | M4 | 2026-03-02 |
| [0003](0003-redis-stock-counters.md) | Redis as source-of-truth for flash-sale stock | M4 | 2026-03-08 |
| [0004](0004-grpc-for-inventory.md) | gRPC (not REST) between API and inventory service | M4 | 2026-03-10 |
| [0005](0005-celery-async-pipeline.md) | Celery for the order-fulfilment pipeline | M5 | 2026-03-22 |
| [0006](0006-nginx-dev-caddy-prod-gateway.md) | Nginx (dev) + Caddy (prod) gateway split | M1 | 2026-05-16 |
| [0007](0007-opentelemetry-grafana-stack.md) | OpenTelemetry + Tempo + Loki + Prometheus + Grafana | M1 | 2026-04-05 |
