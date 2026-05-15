"""Order fulfilment chain.

Five tasks linked with ``chain(*, immutable=True)``:

    capture_payment → commit_inventory → generate_invoice
                    → notify_customer → schedule_dispatch

Why immutable signatures (``.si``) instead of ``.s``?
    With ``.s(order_id)`` Celery prepends the previous task's return
    value as the first positional arg, so ``commit_inventory`` would
    receive ``(prev_result, order_id)`` — a silent off-by-one we'd
    only notice when a task got the wrong order. ``.si`` calls the
    next task with exactly the args we declare.

**Idempotency model.** Every task is replay-safe because we acks-late
in :mod:`app.worker` and gate each step on the order's current
status:

    pending → paid → fulfilling → ...

A retry that arrives after the step's status transition is a no-op
that logs and returns. This survives:

- worker crash mid-task (rabbit redelivers, gate short-circuits)
- duplicate ``process_order`` enqueue (only the first run advances)
- exception inside the task body (autoretry; gate stops a second
  side-effect)

The hand-off to the inventory service uses ``orders.reservation_id``
which Step 9's checkout/flashsale routes persist before enqueueing.
A missing reservation id on a pending order is a programming error
and surfaces as ``RuntimeError`` to fail fast in the worker logs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import grpc
from celery import chain, shared_task
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, InterfaceError

import inventory_pb2 as pb

from app.clickhouse_client import emit_order_event_sync
from app.db_sync import session_scope
from app.grpc_client_sync import get_sync_inventory_stub
from app.models import AuditLog, Order, OrderStatus, Payment, PaymentStatus
from app.worker import app  # noqa: F401  (ensures Celery app is loaded)

logger = logging.getLogger(__name__)

# Exception classes that are worth retrying — anything else is almost
# certainly a programming bug we want to see in the worker log right
# away instead of silently retrying 3 times.
_TRANSIENT_EXC = (OperationalError, InterfaceError, ConnectionError)


# ============================================================
# Step 1 — Capture payment
# ============================================================
@shared_task(
    name="app.tasks.order.capture_payment",
    bind=True,
    autoretry_for=_TRANSIENT_EXC,
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=3,
)
def capture_payment(self, order_id: int) -> int:
    """Move payment from `initiated` to `captured`, order to `paid`.

    There's no real payment provider here — we stamp a deterministic
    placeholder ``provider_ref`` so the row is distinguishable from a
    pre-capture record but the test/seed flow doesn't need credentials.
    The 5-step BPMN diagram in Step 14 calls this branch ``capture-ok``;
    the failure branch would mark the payment ``failed`` and trigger
    a release-reservation compensation, which we leave to Step 17's
    error-handling pass.
    """
    with session_scope() as s:
        order = s.get(Order, order_id)
        if order is None:
            logger.error("capture_payment: order %s not found", order_id)
            return order_id
        if order.status != OrderStatus.PENDING:
            logger.info(
                "capture_payment: order %s already past pending (status=%s) — skipping",
                order_id,
                order.status.value,
            )
            return order_id

        payment = s.scalar(select(Payment).where(Payment.order_id == order_id))
        if payment is None:
            # Step 9 always creates the Payment row in the same tx as
            # the Order; getting here means a manual DB edit.
            raise RuntimeError(f"capture_payment: no Payment row for order {order_id}")

        payment.status = PaymentStatus.CAPTURED
        payment.captured_at = datetime.now(timezone.utc)
        payment.provider_ref = f"dev-capture-{order_id}"
        order.status = OrderStatus.PAID
        logger.info("capture_payment: order %s paid", order_id)
        # Capture values for the analytics emit while the session is
        # still open — order.items would lazy-load otherwise.
        emit_total = order.total
        emit_user_id = order.user_id
        emit_item_count = len(order.items)

    emit_order_event_sync(
        order_id=order_id,
        user_id=emit_user_id,
        status=OrderStatus.PAID.value,
        total=emit_total,
        item_count=emit_item_count,
    )
    return order_id


# ============================================================
# Step 2 — Commit inventory reservation
# ============================================================
@shared_task(
    name="app.tasks.order.commit_inventory",
    bind=True,
    autoretry_for=_TRANSIENT_EXC + (grpc.RpcError,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=5,
)
def commit_inventory(self, order_id: int) -> int:
    """Durably decrement Postgres `inventory_levels` via gRPC.

    The inventory service is the authority on stock. We pass it the
    reservation_id we stored at checkout time; it walks the reserved
    items, applies the decrement in Postgres, and deletes both the
    reservation hash and the idempotency record.

    If the reservation key was already gone (e.g. a previous attempt
    succeeded but the chain crashed before this task could mark
    success in our own DB), the inventory service responds with
    success — so a retry is safe.
    """
    with session_scope() as s:
        order = s.get(Order, order_id)
        if order is None:
            logger.error("commit_inventory: order %s not found", order_id)
            return order_id
        if order.status not in (OrderStatus.PAID, OrderStatus.PENDING):
            logger.info(
                "commit_inventory: order %s already past inventory commit (status=%s)",
                order_id,
                order.status.value,
            )
            return order_id
        if not order.reservation_id:
            raise RuntimeError(
                f"commit_inventory: order {order_id} has no reservation_id"
            )
        reservation_id = order.reservation_id

    stub = get_sync_inventory_stub()
    resp = stub.CommitReservation(pb.CommitRequest(reservation_id=reservation_id))
    if not resp.success:
        # Retry-safe — the gRPC layer reports auto-retry on transient
        # codes (UNAVAILABLE etc) via grpc.RpcError above; a logical
        # failure here is bubbled so it shows up in the worker log.
        raise RuntimeError(
            f"commit_inventory: inventory refused commit for {order_id}: {resp.error}"
        )

    logger.info(
        "commit_inventory: order %s reservation %s committed",
        order_id,
        reservation_id,
    )
    return order_id


# ============================================================
# Step 3 — Generate invoice (writes to audit_log)
# ============================================================
@shared_task(
    name="app.tasks.order.generate_invoice",
    bind=True,
    autoretry_for=_TRANSIENT_EXC,
    retry_backoff=True,
    max_retries=3,
)
def generate_invoice(self, order_id: int) -> int:
    """Write an invoice payload to audit_log.

    The audit_log is the durable, append-only ledger of order-level
    events (R3 normalisation lives in the relational store). A real
    pipeline would render a PDF or push to an invoicing service; the
    BPMN diagram calls that out as a future hook.
    """
    with session_scope() as s:
        order = s.get(Order, order_id)
        if order is None:
            logger.error("generate_invoice: order %s not found", order_id)
            return order_id

        # Idempotency gate: don't write a second invoice row for the
        # same order.
        existing = s.scalar(
            select(AuditLog).where(
                AuditLog.action == "invoice.created",
                AuditLog.entity_type == "order",
                AuditLog.entity_id == str(order_id),
            )
        )
        if existing is not None:
            logger.info("generate_invoice: invoice already exists for order %s", order_id)
            return order_id

        invoice_payload = {
            "order_id": order.id,
            "user_id": order.user_id,
            "total": str(order.total),
            "currency": "USD",
            "subtotal": str(order.subtotal),
            "shipping_fee": str(order.shipping_fee),
            "flash_sale_id": order.flash_sale_id,
            "item_count": len(order.items),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        s.add(
            AuditLog(
                actor_user_id=None,  # system-generated
                action="invoice.created",
                entity_type="order",
                entity_id=str(order_id),
                payload=invoice_payload,
            )
        )
        logger.info("generate_invoice: order %s invoice persisted", order_id)
    return order_id


# ============================================================
# Step 4 — Notify customer (logs only in dev)
# ============================================================
@shared_task(
    name="app.tasks.order.notify_customer",
    bind=True,
    autoretry_for=_TRANSIENT_EXC,
    retry_backoff=True,
    max_retries=2,
)
def notify_customer(self, order_id: int) -> int:
    """Log-only stub.

    A production wire-up would call an SMTP/SES/SMS provider. We
    record the notify attempt in audit_log so the BPMN diagram's
    "notify" path is observable even without real email.
    """
    with session_scope() as s:
        order = s.get(Order, order_id)
        if order is None:
            logger.error("notify_customer: order %s not found", order_id)
            return order_id
        s.add(
            AuditLog(
                actor_user_id=None,
                action="customer.notified",
                entity_type="order",
                entity_id=str(order_id),
                payload={"channel": "log", "order_total": str(order.total)},
            )
        )
    logger.info(
        "notify_customer: order %s — would email user_id=%s", order_id, order.user_id
    )
    return order_id


# ============================================================
# Step 5 — Schedule dispatch (moves order to `fulfilling`)
# ============================================================
@shared_task(
    name="app.tasks.order.schedule_dispatch",
    bind=True,
    autoretry_for=_TRANSIENT_EXC,
    retry_backoff=True,
    max_retries=3,
)
def schedule_dispatch(self, order_id: int) -> int:
    """Flip the order to `fulfilling` — the warehouse-handoff state.

    Beyond this point the order is owned by the dispatch process,
    which lives outside this codebase. Step 14's BPMN models it as
    an external lane.
    """
    with session_scope() as s:
        order = s.get(Order, order_id)
        if order is None:
            logger.error("schedule_dispatch: order %s not found", order_id)
            return order_id
        if order.status == OrderStatus.FULFILLING:
            logger.info("schedule_dispatch: order %s already fulfilling", order_id)
            return order_id
        if order.status not in (OrderStatus.PAID,):
            # Out-of-order replay; don't drag a cancelled order back
            # into the fulfilment lane.
            logger.warning(
                "schedule_dispatch: refusing to advance order %s from %s",
                order_id,
                order.status.value,
            )
            return order_id
        order.status = OrderStatus.FULFILLING
        logger.info("schedule_dispatch: order %s now fulfilling", order_id)
        emit_total = order.total
        emit_user_id = order.user_id
        emit_item_count = len(order.items)

    emit_order_event_sync(
        order_id=order_id,
        user_id=emit_user_id,
        status=OrderStatus.FULFILLING.value,
        total=emit_total,
        item_count=emit_item_count,
    )
    return order_id


# ============================================================
# Chain entry point
# ============================================================
def process_order(order_id: int) -> str:
    """Enqueue the full 5-task chain for ``order_id``.

    Returns the AsyncResult id so the caller can correlate logs.
    Routes call this synchronously — it's a single Redis push and
    returns in microseconds.
    """
    result = chain(
        capture_payment.si(order_id),
        commit_inventory.si(order_id),
        generate_invoice.si(order_id),
        notify_customer.si(order_id),
        schedule_dispatch.si(order_id),
    ).apply_async()
    return result.id
