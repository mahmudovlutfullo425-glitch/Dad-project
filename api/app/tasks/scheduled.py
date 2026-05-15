"""Beat-driven housekeeping jobs.

Four jobs, each idempotent and bounded so a missed tick or a
double-fire from beat is harmless:

- :func:`expire_stuck_pending_orders` (every 5 min) — sweeps orders
  stuck in ``pending`` past 30 min: releases any active reservation,
  refunds the flash-sale per-user counter, marks order ``cancelled``.
- :func:`flash_sale_postmortem` (every 5 min) — flips sales whose
  ``ends_at`` has passed to ``ended`` and writes a short summary
  to ``audit_log``. Step 11 will additionally roll up ClickHouse
  event stats.
- :func:`daily_settlement` (03:00 UTC) — yesterday's order totals
  by status into ``audit_log``.
- :func:`low_stock_alerts` (04:00 UTC) — variants whose on-hand
  count fell below their threshold.

All jobs use the sync session (see :mod:`app.db_sync`); they're
cheap and run far from the request path.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import grpc
import redis as redis_sync
from celery import shared_task
from sqlalchemy import and_, func, select

import inventory_pb2 as pb

from app.clickhouse_client import emit_order_event_sync, query_flash_sale_stats_sync
from app.db_sync import session_scope
from app.grpc_client_sync import get_sync_inventory_stub
from app.models import (
    AuditLog,
    FlashSale,
    FlashSaleStatus,
    InventoryLevel,
    Order,
    OrderStatus,
    ProductVariant,
)

logger = logging.getLogger(__name__)

# 30 minutes is comfortably longer than the 5-minute reservation TTL,
# so the inventory side has already auto-expired the Redis hash by
# the time we sweep — but we still attempt Release in case the
# reservation got refreshed for any reason.
STUCK_THRESHOLD = timedelta(minutes=30)


def _get_sync_redis() -> redis_sync.Redis:
    """Open a fresh sync Redis client for scheduled jobs.

    Cheaper than maintaining a module-level pool because beat runs
    a single tick at a time per task and connections are pooled
    inside redis-py anyway."""
    host = os.getenv("REDIS_HOST", "redis")
    port = int(os.getenv("REDIS_PORT", "6379"))
    return redis_sync.Redis(host=host, port=port, db=0, decode_responses=True)


# ============================================================
# expire_stuck_pending_orders
# ============================================================
@shared_task(name="app.tasks.scheduled.expire_stuck_pending_orders")
def expire_stuck_pending_orders() -> dict:
    """Cancel orders that have been ``pending`` longer than the threshold.

    Why this exists: the Celery chain in :mod:`app.tasks.order` should
    move pending → paid → fulfilling within seconds. If it doesn't,
    the broker is down or a step is failing hard. Sweeping these
    orders releases the stock reservation back into the Redis counter
    so other shoppers aren't locked out.

    Idempotency: we filter on ``status='pending' AND placed_at<cutoff``
    so a double-fire only cancels orders the first run didn't catch.
    """
    cutoff = datetime.now(timezone.utc) - STUCK_THRESHOLD
    cancelled: list[int] = []
    released: list[str] = []

    with session_scope() as s:
        stmt = (
            select(Order)
            .where(Order.status == OrderStatus.PENDING, Order.placed_at < cutoff)
            .order_by(Order.placed_at)
            .limit(200)
        )
        stuck = s.scalars(stmt).all()
        if not stuck:
            return {"cancelled": 0, "released": 0}

        stub = None
        r = None
        for order in stuck:
            # Release the inventory reservation if there's one to
            # release. The inventory service treats an unknown
            # reservation_id as success, so a stale id is safe.
            if order.reservation_id:
                try:
                    if stub is None:
                        stub = get_sync_inventory_stub()
                    stub.ReleaseReservation(
                        pb.ReleaseRequest(reservation_id=order.reservation_id)
                    )
                    released.append(order.reservation_id)
                except grpc.RpcError as exc:
                    logger.warning(
                        "expire_stuck: release failed for order %s (%s): %s",
                        order.id,
                        order.reservation_id,
                        exc.code(),
                    )

            # Flash-sale per-user counter — refund so the user isn't
            # blocked from a retry within their per-user limit.
            if order.flash_sale_id is not None:
                try:
                    if r is None:
                        r = _get_sync_redis()
                    counter_key = f"fs_purchased:{order.flash_sale_id}:{order.user_id}"
                    qty = sum(item.quantity for item in order.items)
                    if qty > 0:
                        r.decrby(counter_key, qty)
                except redis_sync.RedisError as exc:
                    logger.warning(
                        "expire_stuck: counter refund failed for order %s: %s",
                        order.id,
                        exc,
                    )

            order.status = OrderStatus.CANCELLED
            cancelled.append(
                {
                    "order_id": order.id,
                    "user_id": order.user_id,
                    "total": order.total,
                    "item_count": len(order.items),
                }
            )

            s.add(
                AuditLog(
                    actor_user_id=None,
                    action="order.cancelled.stuck",
                    entity_type="order",
                    entity_id=str(order.id),
                    payload={
                        "reservation_id": order.reservation_id,
                        "placed_at": order.placed_at.isoformat(),
                        "age_minutes": int(
                            (datetime.now(timezone.utc) - order.placed_at).total_seconds() / 60
                        ),
                    },
                )
            )

    # Emit analytics after the DB commit so we never publish a
    # `cancelled` event for an order that ended up rolling back.
    for entry in cancelled:
        emit_order_event_sync(
            order_id=entry["order_id"],
            user_id=entry["user_id"],
            status=OrderStatus.CANCELLED.value,
            total=entry["total"],
            item_count=entry["item_count"],
        )

    logger.info(
        "expire_stuck_pending_orders: cancelled=%d released=%d",
        len(cancelled),
        len(released),
    )
    return {"cancelled": len(cancelled), "released": len(released)}


# ============================================================
# flash_sale_postmortem
# ============================================================
@shared_task(name="app.tasks.scheduled.flash_sale_postmortem")
def flash_sale_postmortem() -> dict:
    """Flip just-ended flash sales to ``ended`` and write a summary row.

    Each pass picks up sales whose ``ends_at`` is in the past but whose
    status is still ``scheduled`` or ``active``. The audit_log row is
    a placeholder until Step 11 wires ClickHouse — at that point this
    same task will additionally query the ``flash_sale_events`` table
    and embed the aggregated counts in the payload.
    """
    now = datetime.now(timezone.utc)
    ended_ids: list[int] = []

    with session_scope() as s:
        stmt = select(FlashSale).where(
            FlashSale.ends_at < now,
            FlashSale.status.in_(
                [FlashSaleStatus.SCHEDULED, FlashSaleStatus.ACTIVE]
            ),
        )
        candidates = s.scalars(stmt).all()
        for fs in candidates:
            fs.status = FlashSaleStatus.ENDED
            ended_ids.append(fs.id)

            # Pull aggregated analytics from ClickHouse so the audit_log
            # row carries a self-contained post-mortem rather than just
            # "this sale ended". Falls back gracefully if ClickHouse is
            # down — we still mark the sale ENDED in Postgres.
            stats = query_flash_sale_stats_sync(fs.id)
            payload: dict = {
                "name": fs.name,
                "starts_at": fs.starts_at.isoformat(),
                "ends_at": fs.ends_at.isoformat(),
            }
            if stats is not None:
                payload["analytics_source"] = "clickhouse"
                payload.update(stats)
            else:
                payload["analytics_source"] = "audit_log_only"

            s.add(
                AuditLog(
                    actor_user_id=None,
                    action="flash_sale.ended",
                    entity_type="flash_sale",
                    entity_id=str(fs.id),
                    payload=payload,
                )
            )

    if ended_ids:
        logger.info("flash_sale_postmortem: ended sales %s", ended_ids)
    return {"ended": ended_ids}


# ============================================================
# daily_settlement
# ============================================================
@shared_task(name="app.tasks.scheduled.daily_settlement")
def daily_settlement() -> dict:
    """Aggregate yesterday's orders into a single audit_log row.

    Buckets by status and sums totals. The summary lands in
    ``audit_log`` with ``action='settlement.daily'``; Step 11 will
    additionally write the rollup to ClickHouse for time-series
    queries from Grafana.
    """
    now = datetime.now(timezone.utc)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=1)

    with session_scope() as s:
        stmt = (
            select(
                Order.status,
                func.count(Order.id).label("count"),
                func.coalesce(func.sum(Order.total), Decimal("0")).label("revenue"),
            )
            .where(Order.placed_at >= start, Order.placed_at < end)
            .group_by(Order.status)
        )
        rows = s.execute(stmt).all()
        by_status = {
            row.status.value: {"count": int(row.count), "revenue": str(row.revenue)}
            for row in rows
        }
        total_count = sum(b["count"] for b in by_status.values())
        total_revenue = sum(Decimal(b["revenue"]) for b in by_status.values())

        s.add(
            AuditLog(
                actor_user_id=None,
                action="settlement.daily",
                entity_type="settlement",
                entity_id=start.date().isoformat(),
                payload={
                    "window_start": start.isoformat(),
                    "window_end": end.isoformat(),
                    "by_status": by_status,
                    "totals": {
                        "count": total_count,
                        "revenue": str(total_revenue),
                    },
                },
            )
        )

    logger.info(
        "daily_settlement: %s — %d orders, $%s",
        start.date().isoformat(),
        total_count,
        total_revenue,
    )
    return {
        "date": start.date().isoformat(),
        "order_count": total_count,
        "revenue": str(total_revenue),
    }


# ============================================================
# low_stock_alerts
# ============================================================
@shared_task(name="app.tasks.scheduled.low_stock_alerts")
def low_stock_alerts() -> dict:
    """Audit-log every variant whose on-hand count is below threshold.

    Cheap enough to scan inventory_levels directly. A larger catalog
    would push this to a materialised view; for our ~2000 variants a
    full scan is well under 100ms.
    """
    flagged: list[dict] = []
    with session_scope() as s:
        stmt = (
            select(
                InventoryLevel.variant_id,
                InventoryLevel.quantity_on_hand,
                InventoryLevel.low_stock_threshold,
                ProductVariant.sku,
            )
            .join(ProductVariant, ProductVariant.id == InventoryLevel.variant_id)
            .where(
                and_(
                    InventoryLevel.quantity_on_hand
                    < InventoryLevel.low_stock_threshold,
                    InventoryLevel.low_stock_threshold > 0,
                )
            )
        )
        for variant_id, qoh, threshold, sku in s.execute(stmt).all():
            flagged.append(
                {
                    "variant_id": variant_id,
                    "sku": sku,
                    "quantity_on_hand": int(qoh),
                    "threshold": int(threshold),
                }
            )

        if flagged:
            s.add(
                AuditLog(
                    actor_user_id=None,
                    action="inventory.low_stock",
                    entity_type="inventory",
                    entity_id=datetime.now(timezone.utc).date().isoformat(),
                    payload={"variants": flagged, "flagged_count": len(flagged)},
                )
            )

    logger.info("low_stock_alerts: %d variants below threshold", len(flagged))
    return {"flagged_count": len(flagged)}
