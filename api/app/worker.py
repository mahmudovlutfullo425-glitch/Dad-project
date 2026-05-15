"""Celery application: order-fulfilment chain + scheduled jobs.

Topology:

- **Broker** ``redis://redis:6379/1`` — separate DB from cache/cart
  (db 0) so a FLUSHDB on the cart side never wipes pending tasks.
- **Backend** ``redis://redis:6379/2`` — task results.
- **Worker** runs in compose service ``worker``.
- **Beat** runs in compose service ``beat`` and dispatches the
  scheduled jobs in :mod:`app.tasks.scheduled` against the same
  broker.

Discoverable task modules are listed explicitly via ``include`` —
``autodiscover_tasks`` requires Django-like app config that we do
not have, and being explicit keeps imports predictable.
"""
from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")

BROKER_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/1"
RESULT_BACKEND = f"redis://{REDIS_HOST}:{REDIS_PORT}/2"

app = Celery(
    "ecom",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=[
        "app.tasks.order",
        "app.tasks.scheduled",
    ],
)

app.conf.update(
    # JSON keeps task payloads inspectable in `redis-cli` and refuses
    # to serialise arbitrary Python objects — which catches accidental
    # ORM-instance args at queue time instead of deserialise time.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Acks-late means a task is only removed from the queue *after*
    # the worker reports success. If a worker dies mid-task the message
    # comes back. Combined with our idempotent status-gates in
    # tasks/order.py this gives at-least-once with safe replay.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    # Conservative retry policy — concrete backoff lives on each task.
    task_default_retry_delay=10,
    task_default_max_retries=3,
    broker_connection_retry_on_startup=True,
)

# ----------------------- Beat schedule -----------------------
# Cadence rationale:
#  - stuck-pending sweep every 5 min: catches Celery-chain failures
#    fast enough that a flash-sale reservation (5-min TTL) is still
#    in Redis and can be released cleanly.
#  - flash-sale postmortem every 5 min: catches sales whose ends_at
#    just passed; the audit/clickhouse rollup happens once per sale.
#  - daily settlement at 03:00 UTC and low-stock at 04:00 UTC: avoid
#    the peak-traffic window and stagger to leave room for runtime.
app.conf.beat_schedule = {
    "expire-stuck-pending-orders": {
        "task": "app.tasks.scheduled.expire_stuck_pending_orders",
        "schedule": crontab(minute="*/5"),
    },
    "flash-sale-postmortem": {
        "task": "app.tasks.scheduled.flash_sale_postmortem",
        "schedule": crontab(minute="*/5"),
    },
    "daily-settlement": {
        "task": "app.tasks.scheduled.daily_settlement",
        "schedule": crontab(hour=3, minute=0),
    },
    "low-stock-alerts": {
        "task": "app.tasks.scheduled.low_stock_alerts",
        "schedule": crontab(hour=4, minute=0),
    },
}
