"""OpenTelemetry + Prometheus wiring for the FastAPI service.

A single ``setup_telemetry()`` call from the FastAPI lifespan
configures:

- **Traces** — OTLP/gRPC exporter to the collector at
  ``$OTEL_EXPORTER_OTLP_ENDPOINT``. Auto-instruments FastAPI,
  SQLAlchemy, Redis, and the async gRPC client we use to talk to
  the inventory service.
- **Logs** — Python ``logging`` records are annotated with
  ``trace_id`` / ``span_id`` so Grafana can pivot from a trace to
  the logs of the request that produced it.
- **Metrics** — the prometheus_client default registry (already
  populated by ``app.ratelimit.middleware`` and any other code path
  that creates Counters / Histograms) is exposed on a sidecar HTTP
  server on ``:9000``. Prometheus scrapes that directly so the
  ``/metrics`` surface never reaches the public gateway.

Idempotent: calling twice is a no-op. The ``OTEL_SDK_DISABLED=1``
env var bypasses everything for tests / scripts that don't want
side-effects.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

_initialised = False


def _normalise_grpc_endpoint(raw: str) -> str:
    """Strip http(s) scheme — OTLP/gRPC takes host:port, not a URL."""
    for prefix in ("http://", "https://"):
        if raw.startswith(prefix):
            return raw[len(prefix):]
    return raw


def setup_telemetry(app: "FastAPI", *, service_name: str | None = None) -> None:
    global _initialised
    if _initialised:
        return

    if os.getenv("OTEL_SDK_DISABLED", "").lower() in ("1", "true", "yes"):
        logger.info("telemetry: disabled via OTEL_SDK_DISABLED")
        _initialised = True
        return

    # Heavy imports happen inside the function so the module is
    # cheap to import in contexts (tests, scripts) that don't
    # actually want the SDK.
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from prometheus_client import start_http_server

    endpoint = _normalise_grpc_endpoint(
        os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "otel-collector:4317")
    )
    service_name = service_name or os.getenv("OTEL_SERVICE_NAME", "api")
    namespace = os.getenv("OTEL_SERVICE_NAMESPACE", "ecommerce")

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": namespace,
            "service.version": "1.0.0",
        }
    )

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    )
    trace.set_tracer_provider(provider)

    # --- Auto-instrumentation ------------------------------------------------
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)

    # SQLAlchemy: pass the async engine's underlying sync engine. The
    # event-listener model works whether the engine is wrapped in an
    # AsyncEngine or used directly.
    try:
        from app.db import engine as async_engine

        SQLAlchemyInstrumentor().instrument(
            engine=async_engine.sync_engine, tracer_provider=provider
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("telemetry: sqlalchemy auto-instrument skipped (%s)", exc)

    RedisInstrumentor().instrument(tracer_provider=provider)

    # Async gRPC client — wraps the channel used by checkout / flashsales.
    try:
        from opentelemetry.instrumentation.grpc import GrpcAioInstrumentorClient

        GrpcAioInstrumentorClient().instrument(tracer_provider=provider)
    except Exception as exc:  # noqa: BLE001
        logger.warning("telemetry: grpc client auto-instrument skipped (%s)", exc)

    # Inject trace_id / span_id into every log record so Loki ↔ Tempo
    # correlation works without manual plumbing in every router.
    LoggingInstrumentor().instrument(set_logging_format=True, log_level=logging.INFO)

    # --- Prometheus sidecar --------------------------------------------------
    # Bind to 0.0.0.0:9000 so prometheus (on the same compose
    # network) can reach `api:9000/metrics`. NOT routed through the
    # public gateway.
    metrics_port = int(os.getenv("METRICS_PORT", "9000"))
    try:
        start_http_server(metrics_port)
    except OSError as exc:
        # Replicas binding the same port shouldn't crash startup; just
        # log and continue. Each replica has its own container so the
        # collision case is rare (only matters on local single-process
        # runs where the port might already be taken).
        logger.warning("telemetry: prometheus port %s busy (%s)", metrics_port, exc)

    _initialised = True
    logger.info(
        "telemetry: service=%s exporter=%s metrics_port=%d",
        service_name,
        endpoint,
        metrics_port,
    )
