"""In-memory LLM call telemetry: capture, aggregate, and cost estimation.

Every ``litellm.acompletion`` call funnels through
``llm_request._acompletion_within_timeout`` (see that module's docstring),
so that is the single point recording one physical call's tokens, latency,
and outcome; cache hits/misses are recorded in ``llm_tool_loop`` where the
cache lookup itself happens, and retries of the ``call_llm_json``
schema-repair loop are recorded in ``llm``.

Nothing here writes to a database or a persisted log. AGENTS.md records a
production incident where a per-call write did exactly that: LiteLLM's own
log chatter alone was 9,928 of 20,021 rows in one deployment and starved
the single SQLite writer until ordinary API writes failed with "database
is locked". Telemetry here is aggregated in memory instead, keyed by
(phase, model), and only handed to a caller that asks for a snapshot --
``task_runtime.execute_task_node`` folds one node's snapshot into that
node's own ``ExecutionMetrics`` delta, which is already committed once per
node, not once per call.

Attribution is by "phase": the durable task/node name a call happened
under (e.g. "generate", "review", "safety_screen"), scoped for the
duration of one node's execution via ``scoped_telemetry``. A call made
outside any such scope -- a library caller driving a node function
directly, as the ``dev/`` standalone scripts do -- is still recorded, under
the ``UNSPECIFIED_PHASE`` bucket, so telemetry is never silently dropped;
it just cannot be attributed to a node.
"""

import contextlib
import dataclasses
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from co_scientist.constants_pricing import estimate_cost_usd
from co_scientist.llm_response import extract_token_usage

UNSPECIFIED_PHASE = "unspecified"


@dataclass(frozen=True)
class ModelCallStats:
    """Additive per-(phase, model) telemetry, folded by an accumulator.

    Every field is a delta to sum into a running total, mirroring
    ``models_metrics.MetricDeltas`` -- never a cumulative snapshot on its
    own.

    Attributes:
        calls: Physical completion attempts (successes and failures alike).
        prompt_tokens: Prompt tokens billed across those calls.
        completion_tokens: Completion tokens billed across those calls.
        reasoning_tokens: Reasoning tokens billed separately, when reported.
        cached_prompt_tokens: The share of ``prompt_tokens`` the provider
            served from its prompt cache and billed at its cache-read
            rate. A slice of ``prompt_tokens``, never an addition to it.
            Distinct from ``cache_hits``, which counts this engine's own
            response cache: a call can miss ours and still be almost
            entirely cached at the provider, which is the normal case for
            a tool loop re-sending its transcript.
        cost_usd: Estimated cost in USD (see ``constants_pricing``).
        latency_seconds: Wall-clock time spent in the physical calls.
        retries: ``call_llm_json`` schema-repair retries, distinct from
            ``calls`` (a single retried request may cost several calls).
        cache_hits: Dispatch calls satisfied from the response cache.
        cache_misses: Dispatch calls that reached the provider.
        errors: Failure count by short error-kind string (e.g. the
            exception's class name).
    """

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cached_prompt_tokens: int = 0
    cost_usd: float = 0.0
    latency_seconds: float = 0.0
    retries: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    errors: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Render as a plain, JSON-safe dict for ``ExecutionMetrics``."""
        return dataclasses.asdict(self)


def _add_stats(a: ModelCallStats, b: ModelCallStats) -> ModelCallStats:
    """Sum two ``ModelCallStats``, merging their error-kind counts."""
    errors = dict(a.errors)
    for kind, count in b.errors.items():
        errors[kind] = errors.get(kind, 0) + count
    return ModelCallStats(
        calls=a.calls + b.calls,
        prompt_tokens=a.prompt_tokens + b.prompt_tokens,
        completion_tokens=a.completion_tokens + b.completion_tokens,
        reasoning_tokens=a.reasoning_tokens + b.reasoning_tokens,
        cached_prompt_tokens=(a.cached_prompt_tokens + b.cached_prompt_tokens),
        cost_usd=a.cost_usd + b.cost_usd,
        latency_seconds=a.latency_seconds + b.latency_seconds,
        retries=a.retries + b.retries,
        cache_hits=a.cache_hits + b.cache_hits,
        cache_misses=a.cache_misses + b.cache_misses,
        errors=errors,
    )


class TelemetryAccumulator:
    """Mutable, in-memory ``(phase, model) -> ModelCallStats`` aggregate.

    Scoped to one node's execution by ``scoped_telemetry``; never persisted
    or written anywhere on its own -- see the module docstring.
    """

    def __init__(self) -> None:
        """Start with an empty usage table."""
        self._usage: dict[str, ModelCallStats] = {}

    def record(self, phase: str, model: str, stats: ModelCallStats) -> None:
        """Fold one call's stats into the running (phase, model) total."""
        key = f"{phase}::{model}"
        self._usage[key] = _add_stats(
            self._usage.get(key, ModelCallStats()), stats
        )

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Return the accumulated usage as a plain, JSON-safe dict."""
        return {key: stats.as_dict() for key, stats in self._usage.items()}


_current_accumulator: ContextVar["TelemetryAccumulator | None"] = ContextVar(
    "llm_telemetry_accumulator", default=None
)
_current_phase: ContextVar[str] = ContextVar(
    "llm_telemetry_phase", default=UNSPECIFIED_PHASE
)


@contextlib.contextmanager
def scoped_telemetry(phase: str) -> Iterator[TelemetryAccumulator]:
    """Scope an in-memory telemetry accumulator to one phase's execution.

    Mirrors ``llm_credentials.scoped_api_key``: a context variable rather
    than a mutable global or module-level singleton, so it is inherited by
    any child task spawned (via ``asyncio.gather``/``create_task``) during
    the scoped call, and never leaks into a concurrently-running node or
    run in the same process (see AGENTS.md "No process-global asyncio
    primitives" -- each durable run's worker cohort has its own thread and
    event loop).

    Args:
        phase: The durable task/node name calls made in this scope are
            attributed to (e.g. "generate", "review").

    Yields:
        The accumulator every call made in this scope is recorded into.
    """
    accumulator = TelemetryAccumulator()
    phase_token = _current_phase.set(phase)
    acc_token = _current_accumulator.set(accumulator)
    try:
        yield accumulator
    finally:
        _current_accumulator.reset(acc_token)
        _current_phase.reset(phase_token)


def record_call(model_name: str, stats: ModelCallStats) -> None:
    """Record one call's stats into the active scope, if any.

    A no-op outside any ``scoped_telemetry`` scope, so calling this from a
    caller that never entered one (e.g. a ``dev/`` standalone node script)
    costs nothing -- there is no node boundary to attribute it to.

    Args:
        model_name: Model name in litellm format.
        stats: The delta this call contributes.
    """
    accumulator = _current_accumulator.get()
    if accumulator is None:
        return
    accumulator.record(_current_phase.get(), model_name, stats)


def record_completion_response(
    model_name: str, response: Any, latency_seconds: float
) -> None:
    """Record a successful completion's token usage, cost, and latency.

    Args:
        model_name: Model name in litellm format.
        response: The raw response returned by ``litellm.acompletion``.
        latency_seconds: Wall-clock time the physical call took.
    """
    usage = extract_token_usage(response)
    cost = estimate_cost_usd(
        model_name,
        usage.prompt_tokens,
        usage.completion_tokens,
        usage.cached_prompt_tokens,
    )
    record_call(
        model_name,
        ModelCallStats(
            calls=1,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            cached_prompt_tokens=usage.cached_prompt_tokens,
            cost_usd=cost,
            latency_seconds=latency_seconds,
        ),
    )


def record_completion_failure(
    model_name: str, error: Exception, latency_seconds: float
) -> None:
    """Record a failed completion attempt's latency and error kind.

    Args:
        model_name: Model name in litellm format.
        error: The exception the physical call raised.
        latency_seconds: Wall-clock time spent before it failed.
    """
    record_call(
        model_name,
        ModelCallStats(
            calls=1,
            latency_seconds=latency_seconds,
            errors={type(error).__name__: 1},
        ),
    )


def record_retry(model_name: str) -> None:
    """Record one retry of the ``call_llm_json`` schema-repair loop."""
    record_call(model_name, ModelCallStats(retries=1))


def record_cache_result(model_name: str, hit: bool) -> None:
    """Record a cache lookup outcome for one dispatch call.

    Args:
        model_name: Model name in litellm format.
        hit: Whether the lookup was satisfied from the cache.
    """
    stats = (
        ModelCallStats(cache_hits=1) if hit else ModelCallStats(cache_misses=1)
    )
    record_call(model_name, stats)
