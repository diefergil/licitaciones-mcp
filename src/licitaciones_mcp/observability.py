"""Process-wide observability: structured logging and optional OTel tracing.

This module is intentionally lightweight and dependency-tolerant: the
``opentelemetry`` packages live in the ``[otel]`` optional extra. When they
are not installed we silently skip tracer setup and only configure
``structlog`` for JSON-shaped logs.

Call :func:`configure_observability` once at process startup. Subsequent
calls are idempotent.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, cast

import structlog

from licitaciones_mcp.config import Settings, get_settings

_CONFIGURED = False


def configure_observability(settings: Settings | None = None) -> None:
    """Configure structlog and (optionally) OpenTelemetry exporters.

    Safe to call multiple times; the second invocation is a no-op.
    """

    global _CONFIGURED
    if _CONFIGURED:
        return

    cfg = settings or get_settings()
    level = getattr(logging, cfg.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=level,
    )

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    _maybe_setup_otel(cfg)
    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a configured structlog logger."""

    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


def bind_context(**values: Any) -> None:
    """Bind key/value pairs into the current contextvar log scope."""

    structlog.contextvars.bind_contextvars(**values)


def clear_context() -> None:
    """Clear all contextvar log bindings for the current task."""

    structlog.contextvars.clear_contextvars()


def _maybe_setup_otel(cfg: Settings) -> None:
    """Best-effort OpenTelemetry setup; silently skip if extras are missing."""

    endpoint = cfg.otel_exporter_otlp_endpoint
    if not endpoint:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logging.getLogger(__name__).info(
            "OTEL endpoint set but opentelemetry extras are not installed; "
            "install with `pip install licitaciones-mcp[otel]` to enable tracing"
        )
        return

    resource = Resource.create({"service.name": "licitaciones-mcp"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    try:  # Best-effort auto-instrumentation
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except ImportError:
        pass

    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument()
    except ImportError:
        pass
