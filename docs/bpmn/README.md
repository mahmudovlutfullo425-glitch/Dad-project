# BPMN workflow diagrams (R10)

The R10 rubric item — async pipeline + scheduled jobs — requires a
BPMN diagram for every workflow the pipeline runs. These are
the five (one per `.bpmn` file in this directory).

Each diagram is plain BPMN 2.0 XML produced by hand against the
[bpmn.io](https://demo.bpmn.io/) schema, so it renders unchanged in
the bpmn.io online editor, in `bpmn-js`-based viewers (Camunda
Modeler, draw.io's BPMN shape library), and as embedded images in the
design report.

## The five workflows

| # | Diagram | Triggered by | Code | Brief |
|---|---|---|---|---|
| 1 | [order-fulfilment.bpmn](order-fulfilment.bpmn) | `POST /checkout` and `POST /flashsales/{id}/buy` enqueue `process_order` | [`api/app/tasks/order.py`](../../api/app/tasks/order.py) | 5-task Celery chain: capture_payment → commit_inventory → generate_invoice → notify_customer → schedule_dispatch. Compensation branches (payment failure → release reservation; inventory failure → refund payment) are drawn for design completeness — they are scheduled hardening for step 17. |
| 2 | [flashsale-buy.bpmn](flashsale-buy.bpmn) | `POST /flashsales/{id}/buy` request | [`api/app/routers/flashsales.py`](../../api/app/routers/flashsales.py) | Rate-limit check (429) → time-window check (400) → per-user-limit Redis INCR (400) → gRPC `ReserveStock` (409) → persist Order + Payment → enqueue fulfilment chain → analytics event → 201 response. |
| 3 | [expire-stuck-orders.bpmn](expire-stuck-orders.bpmn) | Celery Beat every 5 min | [`expire_stuck_pending_orders`](../../api/app/tasks/scheduled.py) | Scan `orders` for status=`pending` AND `placed_at < now - 30 min`; for each: gRPC `ReleaseReservation`, refund the flash-sale per-user counter in Redis, set status=`cancelled`, write `order.cancelled.stuck` audit log, emit ClickHouse `cancelled` event. Replaces the spec's "cart expiry" job — carts use Redis TTL and self-expire, so the actual cleanup we need is at the order layer. |
| 4 | [daily-settlement.bpmn](daily-settlement.bpmn) | Celery Beat at 03:00 UTC | [`daily_settlement`](../../api/app/tasks/scheduled.py) | Aggregate yesterday's orders grouped by status; emit one `settlement.daily` audit_log row with `by_status` and `totals` payload. ClickHouse rollup is a planned hook. |
| 5 | [flashsale-postmortem.bpmn](flashsale-postmortem.bpmn) | Celery Beat every 5 min | [`flash_sale_postmortem`](../../api/app/tasks/scheduled.py) | Find sales where `ends_at < now` AND status ∈ {scheduled, active}; for each: query ClickHouse `flash_sale_minute_stats` for accepts/rejects/totals; flip status to `ended`; write `flash_sale.ended` audit log carrying the stats payload (or `analytics_source: audit_log_only` if ClickHouse is unreachable). |

There is also a `low_stock_alerts` job (Celery Beat, 04:00 UTC) that
the spec did not call out — it's a single-task scan with no branching,
not interesting enough to BPMN. Mentioned here for completeness.

## How to view / edit

### Online (zero install)

1. Go to https://demo.bpmn.io/.
2. Drag any `.bpmn` file from this directory onto the page.
3. The diagram renders. Click any shape to see its properties.
4. To edit: drag elements around; export back with `File → Save BPMN diagram`.

### Local (Camunda Modeler)

1. Install Camunda Modeler (free, all platforms): https://camunda.com/download/modeler/
2. `File → Open File` → select any `.bpmn` here.
3. Edit/save as normal.

## How to export PNG for the report

Each `.bpmn` is the canonical source. PNGs go in [`png/`](png/) for the
report's figures.

1. Open the `.bpmn` in https://demo.bpmn.io/.
2. `File → Export as PNG`.
3. Save into `docs/bpmn/png/` with the same base name
   (e.g. `order-fulfilment.png`).
4. Repeat per diagram.

PNGs are gitignored — only the `.bpmn` source is committed, since the
PNG is a build artefact and re-exporting from the source guarantees
they stay in sync. The report's LaTeX/Markdown can either embed the
PNGs or render the `.bpmn` directly with bpmn-js if you're using a web
target.

## Naming conventions inside the files

- IDs are PascalCase prefixed by element kind: `StartEvent_Begin`,
  `ServiceTask_CapturePayment`, `Gateway_PaymentOK`,
  `EndEvent_Fulfilled`, `Flow_Capture_PaymentGW`.
- Sequence-flow `name` attributes carry branch labels (`"ok"`,
  `"payment failed"`, `"429 rate-limited"`) so the viva can read off
  the decision points without zooming in.
- Service tasks are typed `bpmn:serviceTask` (renders with a cog
  icon); plain `bpmn:task` is reserved for orchestration nodes that
  don't call out to an external system.
- Timer-triggered jobs use `bpmn:startEvent` with a
  `bpmn:timerEventDefinition` child carrying a `<bpmn:timeCycle>` in
  ISO 8601 repeating-interval form (`R/PT5M`, `R/PT24H` etc.) so the
  cadence is self-documenting from the XML.

## Layout

Diagrams use Manhattan routing (orthogonal edges) and 100×80 task
shapes at a single y-baseline so the happy path reads left-to-right
without scanning. Error / compensation branches descend vertically
beneath the gateway that triggers them. Coordinates are deliberate;
re-laying-out in bpmn.io is fine if you tweak text but please re-run
the PNG export afterwards.
