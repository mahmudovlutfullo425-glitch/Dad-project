"""Standalone script: rebuild the Meilisearch ``products`` index from Postgres.

Run via ``make reindex``, which mounts this directory and execs the
script inside the api container so ``from app...`` imports resolve.

The algorithm mirrors :func:`app.routers.search._reindex_all` so the
viva can describe one indexing pipeline regardless of trigger.
"""
import asyncio

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import AsyncSessionLocal, engine
from app.models import Product, ProductVariant
from app.search_client import SearchClient, build_search_doc

BATCH_SIZE = 1000


async def main() -> None:
    settings = get_settings()
    client = SearchClient(
        url=f"http://{settings.meili_host}:{settings.meili_port}",
        master_key=settings.meili_master_key,
    )
    await client.ensure_index()

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
    print(f"Indexing {len(docs)} active products...")

    for i in range(0, len(docs), BATCH_SIZE):
        batch = docs[i : i + BATCH_SIZE]
        await client.index_products(batch, wait=True)
        print(f"  batch {i // BATCH_SIZE + 1}: {len(batch)} docs committed")

    await client.close()
    await engine.dispose()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
