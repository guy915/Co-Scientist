from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from litellm.exceptions import ContextWindowExceededError
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from co_scientist.platform.llm import CompletionSpec, LLMCallOptions, call_llm, call_llm_json
from co_scientist.platform.telemetry import tracing
from co_scientist.platform.telemetry.logging_setup import JsonFormatter, RunIdFilter
from tests._llm_fake import make_completion, make_message, scripted_backend

_MODEL = "openrouter/minimax/minimax-m3:free"
_SECRET = "a confidential hypothesis about BRCA1"
_SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing, "_provider", provider)
    yield exporter
    provider.shutdown()


def _named(finished: tuple[ReadableSpan, ...], name: str) -> list[ReadableSpan]:
    return [span for span in finished if span.name == name]


def _parent_id(span: ReadableSpan) -> int | None:
    return span.parent.span_id if span.parent is not None else None


def _span_id(span: ReadableSpan) -> int | None:
    return span.context.span_id if span.context is not None else None


def _attrs(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


def _assert_no_content(finished: tuple[ReadableSpan, ...]) -> None:
    for span in finished:
        assert not span.events
        assert _SECRET not in span.name
        for value in (span.attributes or {}).values():
            assert _SECRET not in str(value)
        assert _SECRET not in (span.status.description or "")


def test_tracing_is_off_without_an_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    assert tracing.configure_tracing() is False
    assert isinstance(tracing.tracer(), trace.NoOpTracer)
    with tracing.current_span("noop", {}):
        assert tracing.current_trace_id() is None


def test_sdk_disabled_wins_over_an_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    assert tracing.configure_tracing() is False


def test_an_endpoint_installs_an_exporting_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.setattr(tracing, "_provider", None)

    try:
        assert tracing.configure_tracing() is True
        assert not isinstance(tracing.tracer(), trace.NoOpTracer)
    finally:
        tracing.shutdown_tracing()
    assert isinstance(tracing.tracer(), trace.NoOpTracer)


@pytest.mark.parametrize("name", tracing.OTLP_HEADER_ENV_VARS)
@pytest.mark.parametrize("value", ["dummy-credential;bad", "dummy-credential%0Ainjected"])
def test_invalid_otlp_headers_disable_tracing_without_logging_credentials(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, name: str, value: str
) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:9")
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.setattr(tracing, "_provider", None)
    monkeypatch.setenv(name, f"Authorization={value}")
    assert tracing.configure_tracing() is False
    assert "invalid OTLP header configuration" in caplog.text
    assert "dummy-credential" not in caplog.text
    assert isinstance(tracing.tracer(), trace.NoOpTracer)


@pytest.mark.parametrize("name", tracing.OTLP_HEADER_ENV_VARS)
def test_valid_otlp_auth_headers_still_configure_tracing(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:9")
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.setattr(tracing, "_provider", None)
    monkeypatch.setenv(name, "Authorization=Basic%20dummy-credential,x-honeycomb-team=dummy-team")
    try:
        assert tracing.configure_tracing() is True
    finally:
        tracing.shutdown_tracing()


async def test_a_logical_call_nests_attempts_and_provider_requests(
    monkeypatch: pytest.MonkeyPatch, spans: InMemorySpanExporter
) -> None:
    usage = make_completion(make_message('{"a": 1}')).usage
    scripted_backend(
        monkeypatch,
        [
            make_completion(make_message("not json")),
            make_completion(make_message('{"a": 1}'), usage=usage),
        ],
    )

    result = await call_llm_json(
        _SECRET,
        CompletionSpec(model_name=_MODEL, max_tokens=1000, json_schema=_SCHEMA),
        max_attempts=2,
        options=LLMCallOptions(prompt_name="ranking.debate"),
    )

    assert result == {"a": 1}
    finished = spans.get_finished_spans()
    (logical,) = _named(finished, "llm.call_llm_json")
    attempts = _named(finished, "llm.attempt")
    requests = _named(finished, f"chat {_MODEL}")
    assert [_attrs(a)["co_scientist.llm.attempt"] for a in attempts] == [1, 2]
    assert {_parent_id(a) for a in attempts} == {_span_id(logical)}
    assert [_parent_id(r) for r in requests] == [_span_id(a) for a in attempts]
    assert _attrs(logical)["gen_ai.request.model"] == _MODEL
    assert _attrs(logical)["co_scientist.llm.prompt_name"] == "ranking.debate"
    assert _attrs(attempts[0])["co_scientist.llm.retry_reason"]
    assert "co_scientist.llm.retry_reason" not in _attrs(attempts[1])
    assert requests[0].kind is trace.SpanKind.CLIENT
    assert _attrs(requests[0])["gen_ai.request.max_tokens"] >= 1000
    assert _attrs(requests[0])["gen_ai.usage.input_tokens"] == 0
    _assert_no_content(finished)


async def test_a_failed_call_records_the_error_type_without_its_message(
    monkeypatch: pytest.MonkeyPatch, spans: InMemorySpanExporter
) -> None:
    scripted_backend(
        monkeypatch,
        [ContextWindowExceededError(message=_SECRET, model=_MODEL, llm_provider="openrouter")],
    )

    with pytest.raises(ContextWindowExceededError):
        await call_llm(_SECRET, CompletionSpec(model_name=_MODEL), max_attempts=1)

    finished = spans.get_finished_spans()
    (logical,) = _named(finished, "llm.call_llm")
    (request,) = _named(finished, f"chat {_MODEL}")
    for span in (logical, request):
        assert span.status.status_code is trace.StatusCode.ERROR
        assert _attrs(span)["error.type"] == "ContextWindowExceededError"
    _assert_no_content(finished)


def test_log_lines_carry_the_active_trace_id(spans: InMemorySpanExporter) -> None:
    def formatted() -> dict[str, object]:
        record = logging.LogRecord("t", logging.INFO, __file__, 1, "message", None, None)
        RunIdFilter().filter(record)
        return dict(json.loads(JsonFormatter().format(record)))

    assert "trace_id" not in formatted()
    with tracing.current_span("outer", {}) as span:
        line = formatted()
    assert line["trace_id"] == trace.format_trace_id(span.get_span_context().trace_id)
