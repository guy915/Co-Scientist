"""In-memory LLM call telemetry: capture, aggregate, and cost estimation.

Every ``litellm.acompletion`` call funnels through
``llm.request.completion._acompletion_within_timeout`` (see that module's
docstring), so that is the single point recording one physical call's tokens,
latency, and outcome; cache hits/misses are recorded in ``llm.precall`` where
the cache lookup itself happens, and retries of ``call_llm_json``'s
schema-repair loop and ``call_llm``'s own budget-escalation loop (see
``llm.attempts.text_retry``) are both recorded here via ``record_retry``.

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
outside any such scope is not captured. Evaluation runners must establish
a scope explicitly; importing this module alone does not collect evidence.
"""

import contextlib
import dataclasses
from collections import Counter
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from co_scientist.constants_pricing import MODEL_PRICING, estimate_cost_usd
from co_scientist.llm.request.response import extract_token_usage

UNSPECIFIED_PHASE = "unspecified"


@dataclass(frozen=True)
class ModelCallStats:
    """Additive per-(phase, model) telemetry, folded by an accumulator.

    Every field is a delta to sum into a running total, mirroring
    ``models_metrics.MetricDeltas`` -- never a cumulative snapshot on its
    own.

    Attributes:
        deterministic_fallbacks: Substituted judgments by reason, independent
            of physical call counts and attributed to the requested model.
        calls: Physical completion attempts (successes and failures alike).
        observed_model_calls: Responses with a nonempty provider model identity.
        reported_usage_calls: Responses with explicit valid token counts.
        priced_usage_calls: Calls with observed identity, token counts and a
            static pricing entry. This supports an estimate, not a bill.
            Calls minus this count have incomplete cost evidence, including
            failures and old checkpoints without observation fields.
        requested_models: Physical attempts by requested model, independent
            of the response model used as the aggregate key.
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
        retries: Retries of either LLM retry loop -- ``call_llm_json``'s
            schema-repair loop or ``call_llm``'s own budget-escalation loop
            -- distinct from ``calls`` (a single retried request may cost
            several calls).
        cache_hits: Dispatch calls satisfied from the response cache.
        cache_misses: Dispatch calls that reached the provider.
        errors: Failure count by short error-kind string (e.g. the
            exception's class name).
    """

    deterministic_fallbacks: dict[str, int] = field(default_factory=dict)
    calls: int = 0
    observed_model_calls: int = 0
    reported_usage_calls: int = 0
    priced_usage_calls: int = 0
    requested_models: dict[str, int] = field(default_factory=dict)
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
        deterministic_fallbacks=dict(
            Counter(a.deterministic_fallbacks)
            + Counter(b.deterministic_fallbacks)
        ),
        calls=a.calls + b.calls,
        observed_model_calls=a.observed_model_calls + b.observed_model_calls,
        reported_usage_calls=a.reported_usage_calls + b.reported_usage_calls,
        priced_usage_calls=a.priced_usage_calls + b.priced_usage_calls,
        requested_models=dict(
            Counter(a.requested_models) + Counter(b.requested_models)
        ),
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

    Mirrors ``llm.admission.credentials.scoped_api_key``: a context variable
    rather than a mutable global or module-level singleton, so it is inherited
    by any child task spawned (via ``asyncio.gather``/``create_task``) during
    the scoped call, and never leaks into a concurrently-running node or run in
    the same process (see AGENTS.md "No process-global asyncio primitives" --
    each durable run's worker cohort has its own thread and event loop).

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


@contextlib.contextmanager
def scoped_telemetry_phase(sub_phase: str) -> Iterator[None]:
    """Attribute one span of a node's calls to a named sub-phase.

    A node that makes several *kinds* of call folds them all into one
    ``(phase, model)`` bucket, and that bucket is the only usage record a
    production run leaves behind on the success path -- nothing logs a
    single call's tokens unless it fails. So a node whose calls are
    unequal (a large synthesis draft beside a small verdict, or beside a
    wave of writing calls) cannot be sized from its own telemetry, which
    is how the research-overview draft's budget ended up reasoned about
    rather than measured.

    Nesting ``scoped_telemetry`` does not fix that: it starts a *fresh*
    accumulator, so the inner numbers never reach the outer snapshot that
    ``task_runtime.execute_task_node`` folds into the node's metrics --
    the sub-phase would be measurable only by a caller holding the inner
    accumulator, and lost from the run. This relabels the phase and keeps
    the same accumulator, so the sub-phase gets its own key *inside* the
    node's own snapshot.

    Safe under ``asyncio.gather``: each task runs on its own copy of the
    context, so a sub-phase set inside one concurrent call does not leak
    into its siblings.

    Args:
        sub_phase: The span's own name, appended to the enclosing phase
            with a dot (e.g. "research_overview.knowledge_base").

    Yields:
        None -- calls are recorded through the enclosing accumulator.
    """
    token = _current_phase.set(f"{_current_phase.get()}.{sub_phase}")
    try:
        yield
    finally:
        _current_phase.reset(token)


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


def _served_model_name(requested: str, response: Any) -> str:
    """The model that answered, falling back to the one requested.

    Args:
        requested: Model name in litellm format, as sent.
        response: The raw response returned by ``litellm.acompletion``.

    Returns:
        The served model carrying the route it was reached by, else
        ``requested``. A gateway rewrites this field to the rung that
        actually served the call -- the only signal distinguishing a
        primary from its fallback after the fact -- but names it without
        the route prefix, so ``openrouter/z-ai/glm-5.3-flash`` returns as
        ``z-ai/glm-5.3-flash``. That matches no key in ``MODEL_PRICING``,
        and taking it at face value prices every call at zero, which is
        the same failure as reading the requested name and was measured
        the same way: a live run of 53 calls, all $0.0000. The route is a
        property of how the call was billed, so it is carried across from
        the request; only the model half comes from the response.
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


def record_completion_response(
    model_name: str, response: Any, latency_seconds: float
) -> None:
    """Record a successful completion's token usage, cost, and latency.

    Cost and tokens are attributed to the model that *answered*, which is
    not always the one asked for: a gateway walking a fallback chain
    answers with whichever rung served the call, and it walks that chain
    precisely when the primary is unavailable. Pricing the requested name
    reports what the configured model would have cost rather than what was
    billed -- a run configured for a free primary reported $0.00 across
    226 calls while the gateway was serving a $1.25/$4.25 fallback, and
    the account was billed $5.23. The requested name is kept only when the
    provider names nothing, since not every one echoes the served model
    and a missing field must not blank out a run's attribution.

    Args:
        model_name: Model name in litellm format, as requested.
        response: The raw response returned by ``litellm.acompletion``.
        latency_seconds: Wall-clock time the physical call took.
    """
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
            priced_usage_calls=int(
                observed and usage_reported and served in MODEL_PRICING
            ),
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
            requested_models={model_name: 1},
            latency_seconds=latency_seconds,
            errors={type(error).__name__: 1},
        ),
    )


def record_retry(model_name: str) -> None:
    """Record one retry of an LLM retry loop.

    Called from both ``call_llm_json``'s schema-repair loop and
    ``call_llm``'s own budget-escalation loop (see ``llm.attempts.text_retry``).
    """
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


def record_deterministic_fallback(model_name: str, reason: str) -> None:
    """Record a substituted judgment against its requested model, not a call.

    Counts describe recorded events only; absent events in old checkpoints
    cannot establish that all judgments came from a model.
    """
    record_call(model_name, ModelCallStats(deterministic_fallbacks={reason: 1}))
