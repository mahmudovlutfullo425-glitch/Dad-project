"""FastAPI application entrypoint.

Wires up routers, OpenAPI metadata, CORS, the shared Redis + Meilisearch
client lifespan, and a liveness probe.
Run with: `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.clickhouse_client import close_clickhouse, init_clickhouse
from app.config import get_settings
from app.grpc_client import close_inventory_client, init_inventory_client
from app.observability import setup_telemetry
from app.ratelimit.redis_backend import RedisBucketStore
from app.redis_client import close_redis, get_redis, init_redis
from app.routers import admin_analytics as admin_analytics_router
from app.routers import auth as auth_router
from app.routers import cart as cart_router
from app.routers import checkout as checkout_router
from app.routers import flashsales as flashsales_router
from app.routers import orders as orders_router
from app.routers import products as products_router
from app.routers import search as search_router
from app.search_client import close_search, init_search

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open shared external clients on startup, close them on shutdown.

    Order matters: cheap dependencies first (Redis), then Meilisearch
    (which pushes index settings), then the inventory gRPC channel
    (lazy — no I/O at init time). Shutdown reverses the order."""
    await init_redis()
    await init_search()
    await init_inventory_client()
    # ClickHouse is best-effort — init logs and continues if the
    # service is down so the storefront still boots.
    await init_clickhouse()
    # Build the rate-limit bucket store on top of the shared Redis
    # client and hang it off app.state so dependency functions in
    # app.ratelimit.middleware can reach it via request.app.state.
    app.state.bucket_store = RedisBucketStore(await get_redis())
    yield
    await close_clickhouse()
    await close_inventory_client()
    await close_search()
    await close_redis()


tags_metadata = [
    {"name": "auth", "description": "Registration, login, current user."},
    {"name": "products", "description": "Catalog browsing and (admin) product management."},
    {"name": "cart", "description": "Live shopping cart backed by Redis (7-day TTL)."},
    {"name": "search", "description": "Full-text product search (Meilisearch) with facets."},
    {"name": "checkout", "description": "Cart → inventory reservation → order placement."},
    {"name": "orders", "description": "Order history and detail."},
    {"name": "flashsales", "description": "Flash sales: list, detail, rate-limited fast-buy path."},
    {"name": "admin", "description": "Admin-only endpoints (analytics, ops)."},
    {"name": "system", "description": "Health and platform probes."},
]

app = FastAPI(
    title="Flash-Sale E-commerce API",
    description=(
        "REST API for the Database Application and Design course project. "
        "Covers users, catalog, carts, flash sales, and orders. Polyglot "
        "persistence (Redis, Meilisearch, ClickHouse) is layered in later steps."
    ),
    version="1.0.0",
    openapi_tags=tags_metadata,
    lifespan=lifespan,
    # Behind the Nginx gateway, the public mount point is /api. Telling
    # FastAPI lets Swagger UI's "Try it out" prepend /api/ to every
    # request, while the app's internal routes stay at root (so the
    # gateway's prefix-strip rewrite still lands them correctly).
    root_path=os.getenv("API_ROOT_PATH", ""),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Wire OpenTelemetry traces + Prometheus metrics. This must run AFTER
# the FastAPI app and middleware are defined (FastAPIInstrumentor
# attaches to the ASGI app) but BEFORE any request handlers fire.
# Called here at module level so it runs once per worker process at
# import time — uvicorn imports `app.main:app` exactly once per worker.
setup_telemetry(app, service_name=os.getenv("OTEL_SERVICE_NAME", "api"))

app.include_router(auth_router.router)
app.include_router(products_router.router)
app.include_router(cart_router.router)
app.include_router(search_router.router)
app.include_router(checkout_router.router)
app.include_router(orders_router.router)
app.include_router(flashsales_router.router)
app.include_router(admin_analytics_router.router)


@app.get("/health", tags=["system"], summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok"}
