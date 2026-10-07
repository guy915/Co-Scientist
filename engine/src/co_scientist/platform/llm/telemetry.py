"""Aggregate in memory and commit once per node; per-call writes starve
SQLite's single writer.
"""

import contextlib
from collections import Counter
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

from co_scientist.core._context import _bind_contextvar
from co_scientist.core.metrics import ModelCallStats
from co_scientist.platform.llm.profile import MODEL_PRICING, estimate_cost_usd
from co_scientist.platform.llm.request.response import extract_token_usage

UNSPECIFIED_PHASE = "unspecified"


def _add_stats(a: ModelCallStats, b: ModelCallStats) -> ModelCallStats:
    errors = dict(a.errors)
    for kind, count in b.errors.items():
        errors[kind] = errors.get(kind, 0) + count
    return ModelCallStats(
        deterministic_fallbacks=dict(
            Counter(a.deterministic_fallbacks) + Counter(b.deterministic_fallbacks)
        ),
        calls=a.calls + b.calls,
        observed_model_calls=a.observed_model_calls + b.observed_model_calls,
        reported_usage_calls=a.reported_usage_calls + b.reported_usage_calls,
        priced_usage_calls=a.priced_usage_calls + b.priced_usage_calls,
        requested_models=dict(Counter(a.requested_models) + Counter(b.requested_models)),
        prompt_tokens=a.prompt_tokens + b.prompt_tokens,
        completion_tokens=a.completion_tokens + b.completion_tokens,
        reasoning_tokens=a.reasoning_tokens + b.reasoning_tokens,
        cached_prompt_tokens=(a.cached_prompt_tokens + b.cached_prompt_tokens),
        cost_usd=a.cost_usd + b.cost_usd,
        latency_seconds=a.latency_seconds + b.latency_seconds,
        retries=a.retries + b.retries,
        errors=errors,
    )


class TelemetryAccumulator:
    def __init__(self) -> None:
        self._usage: dict[str, ModelCallStats] = {}

    def record(self, phase: str, model: str, stats: ModelCallStats) -> None:
        key = f"{phase}::{model}"
        self._usage[key] = _add_stats(self._usage.get(key, ModelCallStats()), stats)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {key: stats.as_dict() for key, stats in self._usage.items()}


_current_accumulator: ContextVar["TelemetryAccumulator | None"] = ContextVar(
    "llm_telemetry_accumulator", default=None
)
_current_phase: ContextVar[str] = ContextVar("llm_telemetry_phase", default=UNSPECIFIED_PHASE)


@contextlib.contextmanager
def scoped_telemetry(phase: str) -> Iterator[TelemetryAccumulator]:
    """Child tasks inherit the accumulator; concurrent runs retain isolated
    task contexts.
    """
    accumulator = TelemetryAccumulator()
    phase_token = _current_phase.set(phase)
    acc_token = _current_accumulator.set(accumulator)
    try:
        yield accumulator
    finally:
        _current_accumulator.reset(acc_token)
        _current_phase.reset(phase_token)


@contextlib.contextmanager
def scoped_telemetry_phase(sub_phase: str) -> Iterator[None]:
    """Relabel within the same accumulator; nested fresh scopes lose inner
    usage from node snapshots.
    """
    with _bind_contextvar(_current_phase, f"{_current_phase.get()}.{sub_phase}"):
        yield


def record_call(model_name: str, stats: ModelCallStats) -> None:
    accumulator = _current_accumulator.get()
    if accumulator is None:
        return
    accumulator.record(_current_phase.get(), model_name, stats)


def _served_model_name(requested: str, response: Any) -> str:
    """Gateway replies omit the billing-route prefix; preserve it or known
    prices become zero.
    """
    served = getattr(response, "model", None)
    if not isinstance(served, str) or not served.strip():
        return requested
    served = served.strip()
    route, _, _ = requested.partition("/")
    if route and requested != served and not served.startswith(f"{route}/"):
        return f"{route}/{served}"
    return served


def _has_token_counts(response: Any) -> bool:
    usage = getattr(response, "usage", None)
    return all(
        type(value := getattr(usage, name, None)) is int and value >= 0
        for name in ("prompt_tokens", "completion_tokens")
    )


def record_completion_response(model_name: str, response: Any, latency_seconds: float) -> None:
    """Attribute spend to the served fallback, not the requested primary."""
    usage = extract_token_usage(response)
    reported = getattr(response, "model", None)
    observed = isinstance(reported, str) and bool(reported.strip())
    usage_reported = _has_token_counts(response)
    served = _served_model_name(model_name, response)
    cost = estimate_cost_usd(
        served,
        usage.prompt_tokens,
        usage.completion_tokens,
        usage.cached_prompt_tokens,
    )
    record_call(
        served,
        ModelCallStats(
            calls=1,
            observed_model_calls=int(observed),
            reported_usage_calls=int(usage_reported),
            priced_usage_calls=int(observed and usage_reported and served in MODEL_PRICING),
            requested_models={model_name: 1},
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            cached_prompt_tokens=usage.cached_prompt_tokens,
            cost_usd=cost,
            latency_seconds=latency_seconds,
        ),
    )


def record_completion_failure(
    model_name: str, error: BaseException, latency_seconds: float
) -> None:
    record_call(
        model_name,
        ModelCallStats(
            calls=1,
            requested_models={model_name: 1},
            latency_seconds=latency_seconds,
            errors={type(error).__name__: 1},
        ),
    )


def record_retry(model_name: str) -> None:
    record_call(model_name, ModelCallStats(retries=1))


def record_deterministic_fallback(model_name: str, reason: str) -> None:
    """Missing old-checkpoint events do not prove that every judgment came
    from a model.
    """
    record_call(model_name, ModelCallStats(deterministic_fallbacks={reason: 1}))
