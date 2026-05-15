"""OpenTelemetry + Prometheus wiring for the inventory gRPC service.

Mirrors the api side (see ``api/app/observability.py``) but targets
a gRPC server rather than a FastAPI app. The same trace pipeline
applies — OTLP/gRPC to the collector, auto-instrumentation for the
common libraries, ``trace_id`` injected into logs.

Custom Prometheus metrics declared here (used by ``app.service``
and the rate-limit interceptor):

- ``stock_decrement_latency_seconds`` — histogram, observed around
  the atomic Redis Lua reserve call inside ``ReserveStock``. This
  is the headline R6 latency panel for the flash-sale dashboard.
- ``rate_limit_rejected_total`` / ``rate_limit_allowed_total`` —
  per-rule counters incremented by the gRPC interceptor.
"""
from __future__ import annotations

import logging
import os

from prometheus_client import Counter, Histogram, start_http_server

logger = logging.getLogger(__name__)

_initialised = False

# ---- Custom metrics (module-level so they survive across calls) ----
STOCK_DECREMENT_LATENCY = Histogram(
    "stock_decrement_latency_seconds",
    "Time taken to atomically decrement Redis stock counters via Lua.",
    buckets=(0.0005, 0.001, 0.002, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

RATE_LIMIT_REJECTED = Counter(
    "rate_limit_rejected_total",
    "gRPC rate-limit rejections by rule.",
    ["rule"],
)

RATE_LIMIT_ALLOWED = Counter(
    "rate_limit_allowed_total",
    "gRPC rate-limit checks that allowed the call.",
    ["rule"],
)


def _normalise_grpc_endpoint(raw: str) -> str:
    """Strip http(s) scheme — OTLP/gRPC takes host:port, not a URL."""
    for prefix in ("http://", "https://"):
        if raw.startswith(prefix):
            return raw[len(prefix):]
    return raw


def setup_telemetry(*, service_name: str | None = None, metrics_port: int = 9000) -> None:
    """Configure tracing + start the Prometheus HTTP server.

    Called early in the inventory service's ``serve()`` coroutine —
    before the gRPC server starts listening so spans cover the very
    first RPC.
    """
    global _initialised
    if _initialised:
        return

    if os.getenv("OTEL_SDK_DISABLED", "").lower() in ("1", "true", "yes"):
        logger.info("telemetry: disabled via OTEL_SDK_DISABLED")
        _initialised = True
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    endpoint = _normalise_grpc_endpoint(
        os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "otel-collector:4317")
    )
    service_name = service_name or os.getenv("OTEL_SERVICE_NAME", "inventory")
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

    # --- gRPC server auto-instrumentation -----------------------------------
    # Must run BEFORE `grpc.aio.server(...)` is created so the interceptor
    # gets installed. server.py calls setup_telemetry() before constructing
    # the server, so this ordering is satisfied.
    try:
        from opentelemetry.instrumentation.grpc import GrpcAioInstrumentorServer

        GrpcAioInstrumentorServer().instrument(tracer_provider=provider)
    except Exception as exc:  # noqa: BLE001
        logger.warning("telemetry: grpc server auto-instrument skipped (%s)", exc)

    # --- SQLAlchemy / Redis auto-instrumentation ----------------------------
    try:
        from app.db import engine as async_engine

        SQLAlchemyInstrumentor().instrument(
            engine=async_engine.sync_engine, tracer_provider=provider
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("telemetry: sqlalchemy auto-instrument skipped (%s)", exc)

    RedisInstrumentor().instrument(tracer_provider=provider)

    LoggingInstrumentor().instrument(set_logging_format=True, log_level=logging.INFO)

    # --- Prometheus sidecar -------------------------------------------------
    try:
        start_http_server(metrics_port)
    except OSError as exc:
        logger.warning("telemetry: prometheus port %s busy (%s)", metrics_port, exc)

    _initialised = True
    logger.info(
        "telemetry: service=%s exporter=%s metrics_port=%d",
        service_name,
        endpoint,
        metrics_port,
    )


def get_tracer():
    """Convenience accessor for modules that need a tracer reference
    without re-importing the opentelemetry package."""
    from opentelemetry import trace

    return trace.get_tracer("inventory")
