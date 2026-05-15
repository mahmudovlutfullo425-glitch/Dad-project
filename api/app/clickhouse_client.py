"""ClickHouse client wrappers + analytics emit helpers.

Two clients, both lazy-initialised:

- **Async** (``get_async_clickhouse``) — used by FastAPI routes via
  ``asyncio.create_task`` so a slow / unreachable ClickHouse never
  blocks a checkout response.
- **Sync** (``get_sync_clickhouse``) — used by Celery tasks. The
  task itself is sync, so spinning up an event loop just to write
  a row is wasteful.

**Best-effort semantics.** Analytics writes are non-critical. Every
public emit helper here catches the underlying errors and logs them
at WARNING — the order or fulfilment flow continues regardless. If
ClickHouse is down, we lose visibility, not data we need to function.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

# --- async ---------------------------------------------------------------
_async_client: Any | None = None

# --- sync ----------------------------------------------------------------
_sync_client: Any | None = None


def _ch_config() -> dict[str, Any]:
    return {
        "host": os.getenv("CLICKHOUSE_HOST", "clickhouse"),
        "port": int(os.getenv("CLICKHOUSE_PORT", "8123")),
        "username": os.getenv("CLICKHOUSE_USER", "ecom"),
        "password": os.getenv("CLICKHOUSE_PASSWORD", "ecom_dev_password"),
        "database": os.getenv("CLICKHOUSE_DB", "analytics"),
    }


# ============================================================
# Async client (for FastAPI)
# ============================================================
async def init_clickhouse() -> None:
    """Open the async client. Best-effort — log and continue on failure.

    Called from the FastAPI lifespan. A startup that can't reach
    ClickHouse must still serve the storefront, so we tolerate
    errors here and let the per-emit error handler downgrade
    individual writes."""
    global _async_client
    if _async_client is not None:
        return
    try:
        import clickhouse_connect

        _async_client = await clickhouse_connect.get_async_client(**_ch_config())
        # Sanity ping — if this fails we keep the (broken) handle so
        # subsequent retries don't all pay the connect cost. The emit
        # helpers swallow errors anyway.
        await _async_client.ping()
        logger.info("clickhouse: async client connected")
    except Exception as exc:  # network, auth, anything
        logger.warning("clickhouse: async init failed (%s) — analytics disabled", exc)
        _async_client = None


async def close_clickhouse() -> None:
    global _async_client
    if _async_client is not None:
        try:
            await _async_client.close()
        except Exception:
            pass
        _async_client = None


async def get_async_clickhouse():
    """Returns the async client or None when ClickHouse is unavailable."""
    return _async_client


# ============================================================
# Sync client (for Celery tasks)
# ============================================================
def get_sync_clickhouse():
    """Lazy sync client. Returns None on first failure and stays that way
    until the worker is restarted — re-trying every call would slow
    down every task during an outage."""
    global _sync_client
    if _sync_client is not None:
        return _sync_client
    try:
        import clickhouse_connect

        _sync_client = clickhouse_connect.get_client(**_ch_config())
        _sync_client.ping()
    except Exception as exc:
        logger.warning("clickhouse: sync init failed (%s) — analytics disabled", exc)
        _sync_client = None
    return _sync_client


# ============================================================
# Emit helpers — async (FastAPI routes)
# ============================================================
async def emit_flash_sale_event(
    flash_sale_id: int,
    variant_id: int,
    user_id: int,
    action: str,
    quantity: int,
    latency_ms: int,
    rejection_reason: str = "",
) -> None:
    """Insert one row into ``flash_sale_events``.

    Designed to be called via ``asyncio.create_task(...)`` so the
    HTTP handler doesn't await the network write.
    """
    client = await get_async_clickhouse()
    if client is None:
        return
    try:
        await client.insert(
            "flash_sale_events",
            [
                [
                    datetime.now(timezone.utc),
                    int(flash_sale_id),
                    int(variant_id),
                    int(user_id),
                    action,
                    int(quantity),
                    int(latency_ms),
                    rejection_reason,
                ]
            ],
            column_names=[
                "event_time",
                "flash_sale_id",
                "variant_id",
                "user_id",
                "action",
                "quantity",
                "latency_ms",
                "rejection_reason",
            ],
        )
    except Exception as exc:
        logger.warning(
            "clickhouse: flash_sale_events insert failed (action=%s fs=%s): %s",
            action,
            flash_sale_id,
            exc,
        )


# ============================================================
# Emit helpers — sync (Celery tasks)
# ============================================================
def emit_order_event_sync(
    order_id: int,
    user_id: int,
    status: str,
    total: Decimal,
    item_count: int,
) -> None:
    """Insert one row into ``order_events``. Best-effort."""
    client = get_sync_clickhouse()
    if client is None:
        return
    try:
        client.insert(
            "order_events",
            [
                [
                    datetime.now(timezone.utc),
                    int(order_id),
                    int(user_id),
                    status,
                    Decimal(total),
                    int(item_count),
                ]
            ],
            column_names=[
                "event_time",
                "order_id",
                "user_id",
                "status",
                "total",
                "item_count",
            ],
        )
    except Exception as exc:
        logger.warning(
            "clickhouse: order_events insert failed (order=%s status=%s): %s",
            order_id,
            status,
            exc,
        )


def query_flash_sale_stats_sync(flash_sale_id: int) -> dict | None:
    """Return aggregated stats for one flash sale.

    Used by :func:`app.tasks.scheduled.flash_sale_postmortem` to embed
    a rollup in the ``audit_log``. Returns None on ClickHouse failure
    so the caller can fall back to the audit-only path.
    """
    client = get_sync_clickhouse()
    if client is None:
        return None
    try:
        # Totals by action — wrap in sum() because the SummingMergeTree
        # may not have merged yet.
        totals_q = """
            SELECT action, sum(event_count) AS events, sum(total_quantity) AS qty
            FROM flash_sale_minute_stats
            WHERE flash_sale_id = {fs_id:UInt64}
            GROUP BY action
        """
        totals = client.query(totals_q, parameters={"fs_id": int(flash_sale_id)})

        # Rejection breakdown — read from the raw events table, since
        # rejection_reason isn't in the minute-stats key.
        rejections_q = """
            SELECT rejection_reason, count() AS c
            FROM flash_sale_events
            WHERE flash_sale_id = {fs_id:UInt64} AND action = 'rejected'
            GROUP BY rejection_reason
        """
        rejections = client.query(
            rejections_q, parameters={"fs_id": int(flash_sale_id)}
        )

        return {
            "by_action": {
                row[0]: {"events": int(row[1]), "quantity": int(row[2])}
                for row in totals.result_rows
            },
            "rejections": {row[0] or "(none)": int(row[1]) for row in rejections.result_rows},
        }
    except Exception as exc:
        logger.warning(
            "clickhouse: stats query failed for fs %s: %s", flash_sale_id, exc
        )
        return None
