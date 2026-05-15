"""Async Meilisearch client wrapping the ``products`` index.

This is the polyglot-persistence anchor for R5: typo-tolerant full-text
search with faceted filtering. The relational alternative (Postgres
``tsvector``/GIN + trigram) is slower for the same workload and lacks
a first-class facet pipeline — see the R6 measurements section of the
report for numbers.

The module exposes:

- ``SearchClient`` — thin async wrapper exposing only the operations
  the routers and the reindex script need.
- A module-level singleton, opened in the FastAPI lifespan, and a
  ``get_search`` dependency yielding it.
- ``build_search_doc`` — pure function turning a SQLAlchemy
  ``Product`` (with eager-loaded ``category`` and ``variants``) into
  the JSON shape we index. Shared with ``scripts/reindex_products.py``.
"""
from __future__ import annotations

from typing import Any

from meilisearch_python_sdk import AsyncClient
from meilisearch_python_sdk.errors import MeilisearchApiError

from app.config import get_settings

INDEX_NAME = "products"

# Fields the user can search across in free text.
SEARCHABLE_ATTRIBUTES: list[str] = ["name", "description", "brand", "category_name"]

# Fields usable in `filter=...` expressions and `facets`. Meilisearch
# requires that anything we want to facet on (e.g. ``category_name``,
# ``brand``) be declared filterable, even if the API doesn't actually
# filter on it.
FILTERABLE_ATTRIBUTES: list[str] = [
    "category_id",
    "category_slug",
    "category_name",
    "brand",
    "price",
    "is_active",
    "in_stock",
]

# Fields usable in `sort=...`.
SORTABLE_ATTRIBUTES: list[str] = ["price", "created_at"]


def _is_already_exists(exc: MeilisearchApiError) -> bool:
    """Tolerate "index already exists" so ``ensure_index`` stays idempotent."""
    return getattr(exc, "code", None) == "index_already_exists"


async def _await_task(client: AsyncClient, result: Any) -> None:
    """Wait for a Meilisearch task to finish, if ``result`` is one.

    The SDK changed return types across versions: some operations
    return a ``TaskInfo`` (with ``task_uid``), others return the
    already-resolved object (``AsyncIndex`` from ``create_index`` in
    v7+). This helper handles both — if there's nothing to wait on,
    it's a no-op."""
    task_uid = getattr(result, "task_uid", None)
    if task_uid is not None:
        await client.wait_for_task(task_uid, timeout_in_ms=60_000)


class SearchClient:
    """Async Meilisearch wrapper for the products index.

    Methods are deliberately narrow: callers only get the verbs needed
    to (a) push documents, (b) delete documents, (c) run a search.
    Higher-level concerns (Pydantic shaping, ACL, query building)
    live in the router."""

    def __init__(self, url: str, master_key: str):
        self._client = AsyncClient(url, master_key)

    @property
    def raw(self) -> AsyncClient:
        """Low-level handle for code that needs it (e.g. wait_for_task)."""
        return self._client

    async def ensure_index(self) -> None:
        """Idempotently create the products index and push its settings."""
        try:
            result = await self._client.create_index(INDEX_NAME, primary_key="id")
            await _await_task(self._client, result)
        except MeilisearchApiError as e:
            if not _is_already_exists(e):
                raise

        index = self._client.index(INDEX_NAME)
        for result in [
            await index.update_searchable_attributes(SEARCHABLE_ATTRIBUTES),
            await index.update_filterable_attributes(FILTERABLE_ATTRIBUTES),
            await index.update_sortable_attributes(SORTABLE_ATTRIBUTES),
        ]:
            await _await_task(self._client, result)

    async def index_product(self, doc: dict[str, Any], *, wait: bool = False) -> None:
        """Add or replace a single product document. Fire-and-forget
        unless ``wait=True`` (used by the reindex path)."""
        result = await self._client.index(INDEX_NAME).add_documents([doc])
        if wait:
            await _await_task(self._client, result)

    async def index_products(
        self, docs: list[dict[str, Any]], *, wait: bool = False
    ) -> None:
        if not docs:
            return
        result = await self._client.index(INDEX_NAME).add_documents(docs)
        if wait:
            await _await_task(self._client, result)

    async def delete_product(self, product_id: int, *, wait: bool = False) -> None:
        try:
            result = await self._client.index(INDEX_NAME).delete_document(product_id)
            if wait:
                await _await_task(self._client, result)
        except MeilisearchApiError as e:
            # Deleting a missing document isn't really an error.
            if getattr(e, "code", None) != "document_not_found":
                raise

    async def search(
        self,
        q: str,
        *,
        filters: list[str] | None = None,
        facets: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
        sort: list[str] | None = None,
    ) -> dict[str, Any]:
        index = self._client.index(INDEX_NAME)
        result = await index.search(
            q,
            filter=filters or None,
            facets=facets or None,
            limit=limit,
            offset=offset,
            sort=sort or None,
        )
        return {
            "hits": result.hits,
            "estimated_total_hits": result.estimated_total_hits,
            "processing_time_ms": result.processing_time_ms,
            "facet_distribution": result.facet_distribution or {},
        }

    async def close(self) -> None:
        await self._client.aclose()


# ---------------- Module-level singleton ----------------

_search: SearchClient | None = None


async def init_search() -> None:
    """Open the shared client and apply index settings. Called from lifespan."""
    global _search
    if _search is not None:
        return
    s = get_settings()
    client = SearchClient(
        url=f"http://{s.meili_host}:{s.meili_port}",
        master_key=s.meili_master_key,
    )
    await client.ensure_index()
    _search = client


async def close_search() -> None:
    global _search
    if _search is not None:
        await _search.close()
        _search = None


async def get_search() -> SearchClient:
    """FastAPI dependency yielding the shared search client."""
    if _search is None:
        await init_search()
    assert _search is not None
    return _search


# ---------------- Document builder ----------------

def build_search_doc(product) -> dict[str, Any]:
    """Convert an eager-loaded ``Product`` into a search document.

    Expects ``product.category`` and ``product.variants`` (with each
    variant's ``inventory_level``) already loaded — the caller decides
    the access pattern (single-row vs reindex bulk). ``in_stock`` is
    True whenever any variant has positive on-hand stock."""
    in_stock = any(
        v.inventory_level is not None and v.inventory_level.quantity_on_hand > 0
        for v in product.variants
    )
    if product.variants:
        min_price = float(min(v.price for v in product.variants))
    else:
        min_price = float(product.base_price)
    return {
        "id": product.id,
        "name": product.name,
        "slug": product.slug,
        "description": product.description or "",
        "brand": product.brand or "",
        "base_price": float(product.base_price),
        # `price` is the filterable/sortable field — variant-aware.
        "price": min_price,
        "category_id": product.category_id,
        "category_slug": product.category.slug,
        "category_name": product.category.name,
        "is_active": product.is_active,
        "in_stock": in_stock,
        "created_at": int(product.created_at.timestamp()),
    }
