"""Product search endpoints — Meilisearch-backed.

GET ``/search/products`` is the customer-facing path: free-text query
plus structured filters (category, brand, price range, in-stock) plus
facet counts for the UI's left rail.

POST ``/admin/search/reindex`` is the admin-only rebuild trigger.
Until Celery is wired in Step 10, it runs the reindex via FastAPI's
``BackgroundTasks`` so the response returns 202 immediately and the
work happens after the HTTP cycle.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import AsyncSessionLocal
from app.deps import get_current_admin
from app.models import Product, ProductVariant, User
from app.schemas.search import SearchHit, SearchResponse
from app.search_client import SearchClient, build_search_doc, get_search

router = APIRouter(tags=["search"])


def _escape(value: str) -> str:
    """Escape backslashes and quotes inside a Meilisearch filter literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


@router.get(
    "/search/products",
    response_model=SearchResponse,
    summary="Full-text product search with facets",
)
async def search_products(
    q: str = Query("", description="Free-text query. Empty string = browse all."),
    category_slug: str | None = None,
    brand: str | None = None,
    min_price: float | None = Query(None, ge=0),
    max_price: float | None = Query(None, ge=0),
    in_stock_only: bool = False,
    sort: str | None = Query(
        None,
        description="Optional sort, e.g. 'price:asc', 'price:desc', 'created_at:desc'",
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    client: SearchClient = Depends(get_search),
) -> SearchResponse:
    filters: list[str] = ["is_active = true"]
    if category_slug:
        filters.append(f'category_slug = "{_escape(category_slug)}"')
    if brand:
        filters.append(f'brand = "{_escape(brand)}"')
    if min_price is not None:
        filters.append(f"price >= {min_price}")
    if max_price is not None:
        filters.append(f"price <= {max_price}")
    if in_stock_only:
        filters.append("in_stock = true")

    result = await client.search(
        q=q,
        filters=filters,
        facets=["category_name", "brand"],
        limit=limit,
        offset=offset,
        sort=[sort] if sort else None,
    )

    return SearchResponse(
        hits=[SearchHit(**h) for h in result["hits"]],
        total=result["estimated_total_hits"],
        took_ms=result["processing_time_ms"],
        facets=result["facet_distribution"],
    )


async def _reindex_all(client: SearchClient) -> None:
    """Pull every active product, build the docs, push the batches.

    Identical algorithm to ``scripts/reindex_products.py`` — the script
    is preferred for one-off CLI rebuilds; this background variant
    powers the admin HTTP trigger."""
    async with AsyncSessionLocal() as session:
        stmt = (
            select(Product)
            .options(
                selectinload(Product.category),
                selectinload(Product.variants).selectinload(
                    ProductVariant.inventory_level
                ),
            )
            .where(Product.is_active.is_(True))
        )
        products = (await session.scalars(stmt)).all()

    docs = [build_search_doc(p) for p in products]
    chunk = 1000
    for i in range(0, len(docs), chunk):
        await client.index_products(docs[i : i + chunk], wait=True)


@router.post(
    "/admin/search/reindex",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger a full product reindex (admin)",
)
async def trigger_reindex(
    background: BackgroundTasks,
    _: User = Depends(get_current_admin),
    client: SearchClient = Depends(get_search),
) -> dict:
    background.add_task(_reindex_all, client)
    return {"status": "accepted", "note": "Reindex running in background"}
