"""Create (or refresh) an *active* flash sale for the R6 flash-sale
load test.

The default ``make seed`` flash sale starts in +1h, which is fine for
end-to-end smoke testing but useless for a load run that needs ``now``
to fall inside ``[starts_at, ends_at]``.

This script is idempotent: re-running it bumps the window forward,
resets ``quantity_allocated`` / ``quantity_on_hand`` to large buffers,
and lifts ``per_user_limit`` high enough that 500 concurrent VUs
can't trip it. Safe to run before every load-test run.

Usage::

    docker compose --env-file .env run --rm \\
        -v "$PWD/scripts:/scripts" -w /app -e PYTHONPATH=/app \\
        api python /scripts/create_loadtest_flashsale.py

Or via the Makefile::

    make loadtest-flashsale

After running, restart the inventory service so its bootstrap rebuilds
the ``stock:`` counters in Redis from the updated Postgres values::

    docker compose restart inventory
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from app.config import get_settings
from app.models import (
    FlashSale,
    FlashSaleItem,
    FlashSaleStatus,
    InventoryLevel,
    ProductVariant,
)

LOADTEST_NAME = "Loadtest Flash Sale"
# Buffers sized so a 30s 500-VU run can't drain stock or trip caps,
# even at multi-thousand-RPS sustained throughput.
STOCK_BUFFER = 1_000_000
PER_USER_LIMIT = 100_000
VARIANTS_IN_SALE = 5
SALE_DURATION_MINUTES = 60


def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.sync_database_url)

    with Session(engine) as session:
        now = datetime.now(timezone.utc)
        starts_at = now - timedelta(minutes=1)  # already started — eligible immediately
        ends_at = now + timedelta(minutes=SALE_DURATION_MINUTES)

        fs = session.scalar(select(FlashSale).where(FlashSale.name == LOADTEST_NAME))
        if fs is None:
            fs = FlashSale(
                name=LOADTEST_NAME,
                starts_at=starts_at,
                ends_at=ends_at,
                status=FlashSaleStatus.ACTIVE,
            )
            session.add(fs)
            session.flush()
            print(f"Created new flash sale id={fs.id}")
        else:
            fs.starts_at = starts_at
            fs.ends_at = ends_at
            fs.status = FlashSaleStatus.ACTIVE
            print(f"Refreshed existing flash sale id={fs.id}")

        # Pick the lowest-id active variants — deterministic across
        # seed runs, easy to hardcode as defaults in the k6 script.
        variants = (
            session.scalars(
                select(ProductVariant)
                .order_by(ProductVariant.id)
                .limit(VARIANTS_IN_SALE)
            ).all()
        )
        if not variants:
            print("ERROR: no product variants found. Run `make seed` first.", file=sys.stderr)
            sys.exit(1)

        existing_items = {
            item.variant_id: item
            for item in session.scalars(
                select(FlashSaleItem).where(FlashSaleItem.flash_sale_id == fs.id)
            ).all()
        }

        for v in variants:
            item = existing_items.get(v.id)
            sale_price = (v.price * Decimal("0.5")).quantize(Decimal("0.01"))
            if item is None:
                session.add(
                    FlashSaleItem(
                        flash_sale_id=fs.id,
                        variant_id=v.id,
                        sale_price=sale_price,
                        quantity_allocated=STOCK_BUFFER,
                        per_user_limit=PER_USER_LIMIT,
                    )
                )
            else:
                item.sale_price = sale_price
                item.quantity_allocated = STOCK_BUFFER
                item.per_user_limit = PER_USER_LIMIT

            # Reset the durable inventory row so both Redis-mode bootstrap
            # and Postgres-mode SELECT FOR UPDATE see a huge headroom.
            level = session.get(InventoryLevel, v.id)
            if level is None:
                session.add(
                    InventoryLevel(
                        variant_id=v.id,
                        quantity_on_hand=STOCK_BUFFER,
                        quantity_reserved=0,
                        low_stock_threshold=10,
                    )
                )
            else:
                level.quantity_on_hand = STOCK_BUFFER
                level.quantity_reserved = 0

        session.commit()

        variant_ids = ",".join(str(v.id) for v in variants)
        print()
        print("=" * 60)
        print(f"  Flash sale ready for load testing")
        print(f"  FLASH_SALE_ID={fs.id}")
        print(f"  VARIANT_IDS={variant_ids}")
        print(f"  Window: {starts_at.isoformat()} → {ends_at.isoformat()}")
        print(f"  per_user_limit={PER_USER_LIMIT}, stock_per_variant={STOCK_BUFFER}")
        print("=" * 60)
        print()
        print("Now restart inventory to refresh Redis stock counters:")
        print("    docker compose restart inventory")
        print()


if __name__ == "__main__":
    main()
