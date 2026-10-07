"""Spans stay off unless an OTLP endpoint is configured (ADR-005); span names
and attributes are an operator contract, and never carry prompt or user text.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Iterator
from typing import Any, Final, Protocol

from opentelemetry import trace

logger = logging.getLogger(__name__)

_TRACER_NAME: Final[str] = "co_scientist"
_ENDPOINT_ENV: Final[str] = "OTEL_EXPORTER_OTLP_ENDPOINT"
_DISABLED_ENV: Final[str] = "OTEL_SDK_DISABLED"
_DEFAULT_SERVICE_NAME: Final[str] = "co-scientist-api"


class _Provider(Protocol):
    def get_tracer(self, instrumenting_module_name: str) -> trace.Tracer: ...

    def shutdown(self) -> None: ...


# Kept off the OpenTelemetry global so tests can swap providers per case.
_provider: _Provider | None = None
_NOOP_TRACER: Final[trace.Tracer] = trace.NoOpTracer()


def tracer() -> trace.Tracer:
    if _provider is None:
        return _NOOP_TRACER
    return _provider.get_tracer(_TRACER_NAME)


def tracing_requested() -> bool:
    if os.environ.get(_DISABLED_ENV, "").strip().lower() == "true":
        return False
    return bool(os.environ.get(_ENDPOINT_ENV, "").strip())


def configure_tracing() -> bool:
    global _provider
    if _provider is not None or not tracing_requested():
        return _provider is not None
    # The SDK and exporter ship only in the api image.
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    service = os.environ.get("OTEL_SERVICE_NAME") or _DEFAULT_SERVICE_NAME
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    _provider = provider
    logger.info("tracing enabled for service %s", service)
    return True


def shutdown_tracing() -> None:
    global _provider
    provider, _provider = _provider, None
    if provider is not None:
        provider.shutdown()


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return trace.format_trace_id(context.trace_id)


def mark_error(span: trace.Span, error: BaseException) -> None:
    """Exception messages can quote provider or user text; record the type
    only.
    """
    span.set_attribute("error.type", type(error).__name__)
    span.set_status(trace.StatusCode.ERROR)


@contextlib.contextmanager
def current_span(
    name: str, attributes: dict[str, Any], kind: trace.SpanKind = trace.SpanKind.INTERNAL
) -> Iterator[trace.Span]:
    # The SDK's own exception recording would copy the message into the span.
    with tracer().start_as_current_span(
        name,
        kind=kind,
        attributes=attributes,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except BaseException as error:
            mark_error(span, error)
            raise
