# ADR 0004 — gRPC (not REST) between API and inventory service

- **Status:** Accepted
- **Date:** 2026-03-10
- **Owner:** M4 (Systems Engineer)

## Context

Rubric requirement R7 demands a non-REST inter-service API somewhere
in the system. The inventory service is the natural fit because the
api ↔ inventory call sits on the hot path of every checkout and every
flash-sale buy — exactly the place where any per-request overhead
hurts most.

The four RPCs the inventory service exposes (`CheckStock`,
`ReserveStock`, `CommitReservation`, `ReleaseReservation`) are
internal-only, called millions of times per sale, and need:

- Strict typed contracts so a mismatch fails at compile-time, not at
  request-time.
- Low per-call serialisation cost.
- Predictable error semantics across the service boundary.

## Decision

**gRPC over HTTP/2** with `inventory.proto` as the single source of
truth. Both the api (Python) and the inventory service (Python)
generate their stubs from the same `.proto` at build time.

- Two stub variants in the api: `grpc_client.py` (async, for FastAPI
  routes) and `grpc_client_sync.py` (sync, for Celery tasks via
  psycopg2).
- Inventory service runs an asyncio gRPC server on port `:50051`
  (internal-only; never exposed to the gateway).
- `grpcio-reflection` enabled so we can introspect the service with
  `grpcurl` during the viva demo.
- OTel `opentelemetry-instrumentation-grpc` for trace propagation —
  the trace started in `api` continues into `inventory` and is
  visible as a single tree in Tempo.

## Consequences

**Positive**

- The `.proto` file is the contract; both sides regenerate stubs and
  cannot drift.
- Protobuf binary wire format is ~3× smaller than equivalent JSON
  payloads; HTTP/2 multiplexes many calls over one connection.
- Trace propagation is automatic via the OTel instrumentation.

**Negative**

- Extra build step (`grpc_tools.protoc`) in both Dockerfiles. Mostly
  one-time cost.
- Debugging an interceptor problem is harder than a REST equivalent
  — needs `grpcurl` instead of `curl`.
- gRPC healthcheck would require `grpc-health-probe` binary; we use
  a plain TCP socket check instead.

## Alternatives considered

- **REST for everything.** Cheaper to debug, fits R4 already, but
  would zero R7 — we'd need a different non-REST surface elsewhere,
  and the inventory hot path is the most defensible place for one.
- **GraphQL.** Wrong shape — single endpoint with one query type
  doesn't justify the framework overhead.
- **NATS request-reply.** Already running NATS for event streaming
  but using it for hot-path request-reply mixes concerns and gives
  worse latency than gRPC over HTTP/2.
