"""FastAPI application entrypoint.

Wires up routers, OpenAPI metadata, CORS, and a liveness probe.
Run with: `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import auth as auth_router
from app.routers import products as products_router

settings = get_settings()

tags_metadata = [
    {"name": "auth", "description": "Registration, login, current user."},
    {"name": "products", "description": "Catalog browsing and (admin) product management."},
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


@app.get("/health", tags=["system"], summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok"}
