# ADR 0007 — OpenTelemetry + Tempo + Loki + Prometheus + Grafana

- **Status:** Accepted
- **Date:** 2026-04-05
- **Owner:** M1 (Platform Lead)

## Context

Rubric R12 demands unified observability — traces, logs, and metrics
collected centrally and queryable from one UI. The system has
several services (api ×2, inventory, worker, beat, gateway,
frontend) and the viva will ask "show me one user request flowing
through the stack" — which means the three signals (trace, logs,
metrics) must be **correlatable**, not just available in separate
silos.

Choices fall into three rough buckets:

1. **All-in-one SaaS** (Datadog, New Relic, Honeycomb). Banned —
   needs PaaS-adjacent vendor lock-in, off-platform credentials in
   the deployment.
2. **ELK + Prometheus + Jaeger** — three separate query languages,
   three separate UIs, manual correlation via copy-pasting trace
   IDs.
3. **Grafana ecosystem** (Tempo for traces, Loki for logs,
   Prometheus for metrics, all behind one Grafana). Single query
   UI; Grafana 11 supports trace-to-log and log-to-trace navigation
   natively.

## Decision

**OpenTelemetry Collector** as the single ingestion point for all
three signal types from all services. From the collector:

- **Traces** → Tempo (24 h retention).
- **Logs** → Loki (24 h retention).
- **Metrics** → exposed as a Prometheus exporter on `:8889`;
  Prometheus scrapes the collector plus each service's own `/metrics`
  endpoint (api on `:9000`, inventory on `:9000`).

Every Python service uses `opentelemetry-instrumentation-*` for
FastAPI, SQLAlchemy, gRPC, Celery, Redis, and httpx — propagation
is automatic across the api → inventory gRPC hop.

Grafana is provisioned with all three datasources at first boot and
ships the "Flash-Sale Operations" dashboard pre-baked. Anonymous
access is enabled because the viva demo shouldn't require a login
flow.

## Consequences

**Positive**

- One UI for the entire observability story. A trace span in Tempo
  has a "view logs" button that opens the matching Loki query
  pre-filled with the `trace_id`.
- OTel collector is the abstraction layer — swapping Tempo for Jaeger
  later would only touch one config file.
- Auto-instrumentation handles the boring 80 %; we only write
  manual spans for cross-service business operations.

**Negative**

- Four extra long-running containers on the droplet (collector,
  tempo, loki, prometheus, grafana = 5). Idle RAM ~600 MB total.
- Tempo and Loki are eventually-consistent — a freshly-emitted span
  can take 2–5 s to show in the UI.
- 24 h retention is enough for the viva demo but not for production
  ops; bumping it needs disk that the droplet doesn't have.

## Alternatives considered

- **ELK (Elasticsearch + Kibana) for logs + Jaeger for traces.**
  Three query languages, no native cross-signal correlation, ~3× the
  RAM footprint.
- **Single service like SigNoz.** Newer, fewer integrations; risk
  of running into something unsupported on viva day.
- **Just stdout + `docker logs`.** Acceptable for dev; would fail R12
  outright.
