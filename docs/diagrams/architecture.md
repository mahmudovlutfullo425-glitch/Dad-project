# System architecture

Single source for the architecture diagram. Renders directly in
GitHub thanks to Mermaid. Export to PNG for the design report by
opening this file in [Mermaid Live Editor](https://mermaid.live/),
pasting the block, and using its PNG export — save as
`architecture.png` next to this file.

## Topology

```mermaid
flowchart TB
    classDef external fill:#fff,stroke:#444,stroke-width:1px,color:#000
    classDef gateway  fill:#ffeec9,stroke:#b27600,color:#000
    classDef api      fill:#cdf2cd,stroke:#1b5e1b,color:#000
    classDef service  fill:#cce5ff,stroke:#0a4a8f,color:#000
    classDef data     fill:#f8d7da,stroke:#a40000,color:#000
    classDef async    fill:#e1cffb,stroke:#5b259f,color:#000
    classDef obs      fill:#d0e9e2,stroke:#1a6650,color:#000

    Browser([Browser / mobile]):::external
    Internet((( Internet ))):::external

    subgraph dropletBox [DigitalOcean droplet — 8 GB / 4 vCPU / 24 h grading window]
        direction TB

        subgraph edgeBox [Edge]
            Caddy[Caddy 2.8<br/>auto-TLS<br/>:80 / :443]:::gateway
        end

        subgraph appBox [Application tier]
            ApiA[api-1<br/>FastAPI :8000]:::api
            ApiB[api-2<br/>FastAPI :8000]:::api
            Frontend[Next.js 14<br/>storefront + admin<br/>:3000]:::api
            Inventory[inventory svc<br/>gRPC :50051<br/>token-bucket interceptor]:::service
        end

        subgraph dataBox [Data tier]
            Postgres[(Postgres 16<br/>14 tables · 3 enums)]:::data
            Redis[(Redis 7<br/>stock · carts · buckets · cache)]:::data
            Meili[(Meilisearch 1.10<br/>products index + facets)]:::data
            Click[(ClickHouse 24.8<br/>events + MV)]:::data
            Nats[(NATS JetStream 2.10)]:::data
        end

        subgraph asyncBox [Async pipeline]
            Worker[Celery worker<br/>5-task chain]:::async
            Beat[Celery beat<br/>4 scheduled jobs]:::async
        end

        subgraph obsBox [Observability]
            Otel[OTel collector<br/>:4317]:::obs
            Tempo[Tempo<br/>traces 24 h]:::obs
            Loki[Loki<br/>logs 24 h]:::obs
            Prom[Prometheus<br/>metrics 24 h]:::obs
            Grafana[Grafana<br/>:3001 anon Admin]:::obs
        end
    end

    Browser -->|HTTPS| Internet
    Internet -->|443| Caddy
    Caddy -->|"/api/*"| ApiA
    Caddy -->|"/api/*"| ApiB
    Caddy -->|"/" SSR| Frontend

    ApiA -->|gRPC :50051| Inventory
    ApiB -->|gRPC :50051| Inventory

    ApiA --- Postgres
    ApiA --- Redis
    ApiA --- Meili
    ApiA --- Click
    ApiB --- Postgres
    ApiB --- Redis

    Inventory --- Redis
    Inventory --- Postgres

    Worker --- Redis
    Worker --- Postgres
    Worker --- Inventory
    Worker --- Click
    Beat --- Redis

    ApiA -. OTLP .-> Otel
    ApiB -. OTLP .-> Otel
    Inventory -. OTLP .-> Otel
    Worker -. OTLP .-> Otel

    Otel --> Tempo
    Otel --> Loki
    Otel --> Prom
    Tempo --> Grafana
    Loki --> Grafana
    Prom --> Grafana
```

## Request paths

Three representative flows that the report and viva can step through.

### 1. Browse catalogue (read-heavy, cached)

```mermaid
sequenceDiagram
    actor User
    participant Caddy
    participant API as api (FastAPI)
    participant Redis
    participant Postgres

    User->>Caddy: GET /api/products/42
    Caddy->>API: GET /products/42  (TLS terminated)
    API->>Redis: GET hot:product:42
    alt cache hit
        Redis-->>API: pre-serialised JSON
    else cache miss
        API->>Postgres: SELECT product + variants + category
        Postgres-->>API: rows
        API->>Redis: SET hot:product:42 (TTL 300s)
    end
    API-->>Caddy: 200 OK
    Caddy-->>User: 200 OK
```

### 2. Flash-sale buy (the hot path R6 tests)

```mermaid
sequenceDiagram
    actor User
    participant Caddy
    participant API as api
    participant Limiter as token-bucket
    participant Inv as inventory (gRPC)
    participant Redis
    participant PG as Postgres
    participant Click as ClickHouse
    participant Worker as Celery worker

    User->>Caddy: POST /api/flashsales/1/buy
    Caddy->>API: POST /flashsales/1/buy
    API->>Limiter: try_consume(FLASH_BUY_PER_USER, user_id)
    Limiter->>Redis: EVAL bucket.lua
    Redis-->>Limiter: allowed=1
    API->>Inv: ReserveStock(idempotency_key, items)
    Inv->>Redis: EVAL atomic DECRBY
    Redis-->>Inv: reservation_id
    Inv-->>API: success
    API->>PG: INSERT order + payment
    API->>Click: emit flash_sale_event(accepted)
    API->>Worker: process_order.delay(order_id)
    API-->>Caddy: 200 OK + order_id
    Caddy-->>User: 200 OK

    Note over Worker,PG: Background chain:<br/>capture_payment → commit_inventory →<br/>generate_invoice → notify_customer →<br/>schedule_dispatch
```

### 3. Login under credential-stuffing attack (rate limiter in action)

```mermaid
sequenceDiagram
    actor Attacker
    participant Caddy
    participant API as api
    participant Limiter as token-bucket
    participant Redis

    loop 6 rapid requests
        Attacker->>Caddy: POST /api/auth/login
        Caddy->>API: POST /auth/login
        API->>Limiter: try_consume(LOGIN_PER_IP, src_ip)
        Limiter->>Redis: EVAL bucket.lua
        alt tokens available
            Redis-->>Limiter: allowed=1
            API-->>Attacker: 401 (wrong password)
        else bucket empty
            Redis-->>Limiter: allowed=0, retry_after=20s
            API-->>Attacker: 429 + Retry-After: 20
        end
    end
```

## What lives where in the repo

| Box on the diagram | Source code |
|---|---|
| Caddy | `gateway/Caddyfile`, `gateway/Dockerfile` |
| api ×2 | `api/app/main.py` + `api/app/routers/` |
| inventory svc | `inventory/app/server.py` + `inventory/app/service.py` |
| Frontend | `frontend/app/` (Next.js App Router) |
| Token-bucket | `api/app/ratelimit/` and `inventory/app/ratelimit/` |
| Celery chain | `api/app/tasks/order.py` |
| Celery beat | `api/app/tasks/scheduled.py` |
| ClickHouse schema | `scripts/clickhouse_init.sql` |
| OTel + Grafana | `observability/` |
| Compose orchestration | `docker-compose.yml` |
