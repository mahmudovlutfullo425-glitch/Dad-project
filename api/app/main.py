"""FastAPI application entrypoint.

Wires up routers, OpenAPI metadata, CORS, the shared Redis client
lifespan, and a liveness probe.
Run with: `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.redis_client import close_redis, init_redis
from app.routers import auth as auth_router
from app.routers import cart as cart_router
from app.routers import products as products_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open shared external clients on startup, close them on shutdown."""
    await init_redis()
    yield
    await close_redis()


tags_metadata = [
    {"name": "auth", "description": "Registration, login, current user."},
    {"name": "products", "description": "Catalog browsing and (admin) product management."},
    {"name": "cart", "description": "Live shopping cart backed by Redis (7-day TTL)."},
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

app.include_router(auth_router.router)
app.include_router(products_router.router)
app.include_router(cart_router.router)


@app.get("/health", tags=["system"], summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok"}
