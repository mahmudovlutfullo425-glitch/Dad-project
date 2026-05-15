"""Admin analytics — reads from ClickHouse.

Read-only endpoints that aggregate the ``flash_sale_events`` /
``order_events`` streams. Useful for the design-report screenshots
and as the data source the frontend admin page in Step 15 will
hang off.

Endpoint surface intentionally small: one detail view per flash
sale, totals + per-minute timeline + rejection breakdown. Heavier
slices (cohort analysis, funnel) are out of scope here.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.clickhouse_client import get_async_clickhouse
from app.deps import get_current_admin
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/analytics", tags=["admin"])


def _rows_to_dicts(result) -> list[dict[str, Any]]:
    """Convert clickhouse-connect query result into a list of dicts.

    ``QueryResult`` carries `column_names` and `result_rows`; we zip
    them so callers don't have to remember positional indexing."""
    cols = result.column_names
    return [dict(zip(cols, row)) for row in result.result_rows]


@router.get(
    "/flashsales/{flash_sale_id}",
    summary="Aggregated stats for a single flash sale",
)
async def flashsale_analytics(
    flash_sale_id: int,
    _admin: User = Depends(get_current_admin),
) -> dict[str, Any]:
    client = await get_async_clickhouse()
    if client is None:
        # 503 makes the failure visible to the admin without pretending
        # the sale has zero events.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ClickHouse not available — analytics disabled",
        )

    # Totals by action (attempt / accepted / rejected)
    totals_q = """
        SELECT action, sum(event_count) AS events, sum(total_quantity) AS quantity
        FROM flash_sale_minute_stats
        WHERE flash_sale_id = {fs_id:UInt64}
        GROUP BY action
        ORDER BY action
    """
    # Per-minute timeline — ordered for plotting straight off the wire.
    timeline_q = """
        SELECT toString(minute) AS minute, action,
               sum(event_count) AS events,
               sum(total_quantity) AS quantity
        FROM flash_sale_minute_stats
        WHERE flash_sale_id = {fs_id:UInt64}
        GROUP BY minute, action
        ORDER BY minute, action
    """
    # Rejection breakdown — sourced from raw events because the MV
    # doesn't carry rejection_reason in its key.
    rejections_q = """
        SELECT rejection_reason, count() AS count
        FROM flash_sale_events
        WHERE flash_sale_id = {fs_id:UInt64} AND action = 'rejected'
        GROUP BY rejection_reason
        ORDER BY count DESC
    """
    # p50/p95 latency over the sale window.
    latency_q = """
        SELECT
            quantile(0.5)(latency_ms)  AS p50,
            quantile(0.95)(latency_ms) AS p95,
            quantile(0.99)(latency_ms) AS p99,
            count() AS samples
        FROM flash_sale_events
        WHERE flash_sale_id = {fs_id:UInt64}
    """

    params = {"fs_id": int(flash_sale_id)}
    try:
        totals = await client.query(totals_q, parameters=params)
        timeline = await client.query(timeline_q, parameters=params)
        rejections = await client.query(rejections_q, parameters=params)
        latency = await client.query(latency_q, parameters=params)
    except Exception as exc:
        logger.exception("clickhouse: query failure for fs %s", flash_sale_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ClickHouse query failed: {exc}",
        )

    lat_row = latency.result_rows[0] if latency.result_rows else (0, 0, 0, 0)

    return {
        "flash_sale_id": flash_sale_id,
        "totals": _rows_to_dicts(totals),
        "timeline": _rows_to_dicts(timeline),
        "rejections": _rows_to_dicts(rejections),
        "latency_ms": {
            "p50": float(lat_row[0] or 0),
            "p95": float(lat_row[1] or 0),
            "p99": float(lat_row[2] or 0),
            "samples": int(lat_row[3] or 0),
        },
    }


@router.get(
    "/orders/daily",
    summary="Order counts/revenue per status for the last N days",
)
async def orders_daily(
    days: int = 7,
    _admin: User = Depends(get_current_admin),
) -> dict[str, Any]:
    if days < 1 or days > 90:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="days must be between 1 and 90",
        )

    client = await get_async_clickhouse()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ClickHouse not available",
        )

    query = """
        SELECT
            toString(toDate(event_time)) AS day,
            status,
            count() AS orders,
            sum(total) AS revenue,
            sum(item_count) AS items
        FROM order_events
        WHERE event_time >= now() - INTERVAL {days:UInt32} DAY
        GROUP BY day, status
        ORDER BY day DESC, status
    """
    try:
        result = await client.query(query, parameters={"days": days})
    except Exception as exc:
        logger.exception("clickhouse: daily orders query failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ClickHouse query failed: {exc}",
        )

    return {"days": days, "rows": _rows_to_dicts(result)}
