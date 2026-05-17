# ADR 0005 — Celery for the order-fulfilment pipeline

- **Status:** Accepted
- **Date:** 2026-03-22
- **Owner:** M5 (Pipeline + Frontend)

## Context

After `POST /checkout` returns 200 to the user, the system still has
five things to do, none of which the user should have to wait for:

1. Capture payment with the payment provider.
2. Commit the inventory reservation in the inventory service.
3. Generate an invoice JSON and append to `audit_log`.
4. Notify the customer (email in production; log-only in dev).
5. Schedule the dispatch and mark the order as `fulfilling`.

Doing this inline would tie request latency to the slowest external
dependency (payment provider in particular) and would couple the
checkout success/failure to the success/failure of side-effect work
that the user already paid for. The order is already created in
Postgres before the chain runs — what we need is a durable,
retryable, observable pipeline that finishes the rest in the
background.

Rubric R10 also explicitly demands a pipeline plus 5 BPMN diagrams.

## Decision

**Celery** as the task queue, with **Redis** as both broker and
result backend (no new infrastructure since we already run Redis for
stock counters and rate-limit state).

The chain:

```
capture_payment
   ↓
commit_inventory      ← calls inventory.CommitReservation (gRPC)
   ↓
generate_invoice      ← writes invoice JSON to audit_log
   ↓
notify_customer       ← logs in dev; email in prod
   ↓
schedule_dispatch     ← marks order as `fulfilling`
```

Each step is an autoretry task with exponential backoff
(`max_retries=3`). If `capture_payment` fails after retries, the
order ends up in `payment_failed` and a beat-scheduled sweeper
releases the inventory reservation.

**Beat-scheduled jobs:**

| Task | Schedule | Purpose |
|---|---|---|
| `expire_abandoned_carts` | hourly | Release stale reservations |
| `daily_settlement` | 03:00 UTC | Aggregate yesterday's orders → ClickHouse + audit_log |
| `low_stock_alerts` | 04:00 UTC | Variants below threshold → audit_log |
| `flash_sale_postmortem` | every 5 min | Roll up ended flash sales to ClickHouse |

The corresponding BPMN diagrams live in `docs/bpmn/`.

## Consequences

**Positive**

- Checkout p95 stays under 200 ms regardless of payment-provider
  latency.
- Each task has its own retry policy and is independently observable
  (Prometheus counter + Tempo span).
- Reuses existing Redis; no new infrastructure.

**Negative**

- Two extra long-running containers (`worker` and `beat`).
- A failure between two chain steps (e.g. payment captured but
  inventory commit fails) needs the stuck-order sweeper to clean up.
- Celery's Beat is a single-instance scheduler — not a problem at
  one beat container, but would need locking if scaled.

## Alternatives considered

- **NATS JetStream consumers** instead of Celery. Already running
  NATS for events. Rejected because Celery has better Python-native
  task chaining, retry policies, and beat scheduling — building the
  equivalent on NATS would have been more code with no observability
  advantage.
- **Synchronous fulfilment inline with checkout.** Couples request
  latency to payment-provider latency; one slow request can timeout
  the gateway.
- **AWS SQS / Lambda.** Off the IaaS stack the spec requires.
