"""Execution-metrics models and node state-update helpers.

Split out of ``models`` to keep that module focused on the hypothesis
domain dataclasses; every name here remains importable from
``co_scientist.models`` via re-export shims, so import sites are
unaffected.
"""

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from co_scientist.llm_telemetry import ModelCallStats


def _known_field_kwargs(cls: Any, data: dict[str, Any]) -> dict[str, Any]:
    """Return the items of ``data`` whose keys are fields of ``cls``.

    Dropping unknown keys keeps older serialized payloads loadable if a field
    is later removed; the caller splats the result into ``cls(...)``.

    Args:
        cls: The dataclass whose field names are the allowed keys.
        data: A ``to_dict`` payload, possibly carrying stale keys.

    Returns:
        A dict of ``data`` items restricted to ``cls``'s field names.
    """
    field_names = {f.name for f in dataclasses.fields(cls)}
    return {k: v for k, v in data.items() if k in field_names}


@dataclass
class ExecutionMetrics:
    """Metrics for workflow execution."""

    total_time: float = 0.0
    hypothesis_count: int = 0
    reviews_count: int = 0
    tournaments_count: int = 0
    evolutions_count: int = 0
    llm_calls: int = 0  # Total LLM calls made
    # Keyed by workflow phase/node name (e.g. "generate", "review");
    # wall-clock seconds spent in that phase, summed across calls.
    phase_times: dict[str, float] = field(default_factory=dict)
    # Keyed by "{phase}::{model}" (the durable task/node name and the
    # litellm model name); each value is a plain dict of the fields on
    # ``llm_telemetry.ModelCallStats`` (calls, prompt/completion/reasoning
    # tokens, cost_usd, latency_seconds, retries, cache_hits/misses, and an
    # errors dict keyed by error kind). Populated by
    # ``task_runtime.execute_task_node`` from the in-memory telemetry
    # captured during that node's LLM calls -- see
    # ``co_scientist.llm_telemetry`` for why this is aggregated in memory
    # rather than written per call (AGENTS.md: a per-call database row or
    # persisted log record starves the single SQLite writer).
    model_usage: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Science skill name -> times a node invoked it, summed across the
    # run. Recorded because the skills reach third-party databases whose
    # terms are separate from the bundle's licence and most of which
    # require the user be notified of them; a notice seeded into a
    # temporary workspace reaches nobody, so the run's report attributes
    # the sources it actually used and this is how they get there. Empty
    # on every run that used no skill, which is every run without
    # COSCIENTIST_SKILLS_DIR.
    skills_used: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for checkpoint transport (all fields are plain data)."""
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionMetrics":
        """Rebuild from a ``to_dict`` payload, ignoring unknown keys.

        Ignoring unknown keys keeps older checkpoints loadable if a metric
        field is later removed.
        """
        return cls(**_known_field_kwargs(cls, data))


def _merge_phase_times(
    existing_phase_times: dict[str, float], new_phase_times: dict[str, float]
) -> dict[str, float]:
    """Merge two phase-timing dicts, summing seconds for phases in both.

    Args:
        existing_phase_times: Phase times already accumulated in state.
        new_phase_times: Phase times from a node's metrics delta.

    Returns:
        A new dict with combined wall-clock seconds per phase.
    """
    merged_phase_times = dict(existing_phase_times)

    for phase, time_val in new_phase_times.items():
        merged_phase_times[phase] = (
            merged_phase_times.get(phase, 0.0) + time_val
        )

    return merged_phase_times


def _merge_usage_entry(
    existing_entry: dict[str, Any], new_entry: dict[str, Any]
) -> dict[str, Any]:
    """Sum one (phase, model) usage entry's numeric fields and count maps.

    Every field a ``ModelCallStats.as_dict()`` entry carries is additive
    (see that dataclass), so this is a plain field-by-field sum with the
    "errors" and "requested_models" maps merged by ``_merge_counts``.

    The field list is read off ``ModelCallStats`` rather than restated
    here. A hand-written list is a second place to remember, and the one
    that gets forgotten: fan-out is how the most expensive phase in a run
    aggregates, so a field missing from the list is not partially counted
    but silently zeroed for exactly the phase whose cost matters most.
    """
    numeric_fields = tuple(
        f.name
        for f in dataclasses.fields(ModelCallStats)
        if f.name not in {"errors", "requested_models"}
    )
    merged = {
        field_name: existing_entry.get(field_name, 0)
        + new_entry.get(field_name, 0)
        for field_name in numeric_fields
    }
    merged["errors"] = _merge_counts(
        existing_entry.get("errors", {}), new_entry.get("errors", {})
    )
    merged["requested_models"] = _merge_counts(
        existing_entry.get("requested_models", {}),
        new_entry.get("requested_models", {}),
    )
    return merged


def _merge_model_usage(
    existing_usage: dict[str, dict[str, Any]],
    new_usage: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Merge two ``model_usage`` dicts, summing entries for shared keys.

    Args:
        existing_usage: Usage already accumulated in state.
        new_usage: Usage from a node's telemetry snapshot.

    Returns:
        A new dict with combined per-(phase, model) usage.
    """
    merged = {key: dict(entry) for key, entry in existing_usage.items()}
    for key, new_entry in new_usage.items():
        merged[key] = _merge_usage_entry(merged.get(key, {}), new_entry)
    return merged


def _merge_counts(
    existing: dict[str, int], new: dict[str, int]
) -> dict[str, int]:
    """Sums two name-to-count maps into a new dict."""
    merged = dict(existing)
    for name, count in new.items():
        merged[name] = merged.get(name, 0) + count
    return merged


def merge_metrics(
    existing: ExecutionMetrics, new: ExecutionMetrics
) -> ExecutionMetrics:
    """State reducer that merges metrics from multiple nodes.

    When multiple nodes update metrics concurrently, this combines them. Lives
    next to ExecutionMetrics so field additions and their merge policy are a
    one-file change.

    Args:
        existing: Existing metrics in state
        new: New metrics being added (should contain only deltas)

    Returns:
        Merged metrics (new object, does not mutate inputs)
    """
    # LangGraph invokes this reducer whenever a node's state update includes
    # a "metrics" key; "new" is that node's create_metrics_update(...) output
    # (deltas only), not a cumulative snapshot. Builds a NEW metrics object.
    merged_phase_times = _merge_phase_times(
        existing.phase_times, new.phase_times
    )

    # hypothesis_count is the node's reported running *total* rather than a
    # delta, so max() avoids double-counting; total_time only overwrites
    # when a node measured one (> 0); the rest are additive deltas.
    merged = ExecutionMetrics(
        hypothesis_count=max(existing.hypothesis_count, new.hypothesis_count),
        reviews_count=existing.reviews_count + new.reviews_count,
        tournaments_count=existing.tournaments_count + new.tournaments_count,
        evolutions_count=existing.evolutions_count + new.evolutions_count,
        llm_calls=existing.llm_calls + new.llm_calls,
        total_time=new.total_time
        if new.total_time > 0
        else existing.total_time,
        phase_times=merged_phase_times,
        model_usage=_merge_model_usage(existing.model_usage, new.model_usage),
        skills_used=_merge_counts(existing.skills_used, new.skills_used),
    )

    return merged


@dataclass(frozen=True)
class MetricDeltas:
    """The additive per-node counters one metrics update contributes.

    Each field is a delta the ``merge_metrics`` reducer adds to the
    cumulative run total, not an absolute value.

    Attributes:
        reviews: Reviews produced by this node.
        tournaments: Tournament rounds run by this node.
        evolutions: Evolutions produced by this node.
        llm_calls: LLM calls made by this node.
        skills_used: science skill invocations this node made, by skill
            name.
    """

    reviews: int = 0
    tournaments: int = 0
    evolutions: int = 0
    llm_calls: int = 0
    skills_used: Mapping[str, int] = field(default_factory=dict)


def create_metrics_update(
    hypothesis_count: int | None = None,
    deltas: MetricDeltas | None = None,
    total_time: float | None = None,
    phase_times: dict[str, float] | None = None,
    model_usage: dict[str, dict[str, Any]] | None = None,
) -> ExecutionMetrics:
    """Create new ExecutionMetrics with ONLY the deltas (not cumulative).

    The merge_metrics reducer will add these deltas to the existing state.
    Do NOT pass base metrics - only pass the increments from this node.

    Args:
        hypothesis_count: new total hypothesis count
            (replaces via max(), not adds)
        deltas: additive per-node counters (reviews/tournaments/
            evolutions/llm_calls); defaults to all-zero.
        total_time: new total time (only set if > 0)
        phase_times: new phase times dict (merged with existing)
        model_usage: new per-(phase, model) LLM call usage (merged with
            existing); see ``ExecutionMetrics.model_usage``.

    Returns:
        new ExecutionMetrics object with ONLY deltas
    """
    d = deltas if deltas is not None else MetricDeltas()
    return ExecutionMetrics(
        hypothesis_count=hypothesis_count
        if hypothesis_count is not None
        else 0,
        reviews_count=d.reviews,
        tournaments_count=d.tournaments,
        evolutions_count=d.evolutions,
        llm_calls=d.llm_calls,
        total_time=total_time if total_time is not None else 0.0,
        phase_times=phase_times if phase_times is not None else {},
        model_usage=model_usage if model_usage is not None else {},
        skills_used=dict(d.skills_used),
    )


def phase_message(
    phase: str, content: str, **metadata: Any
) -> list[dict[str, Any]]:
    """Build the one-message list a node returns in its state update.

    Args:
        phase: Workflow phase name recorded in the message metadata.
        content: Human-readable summary of what the node did.
        **metadata: Extra metadata fields merged alongside the phase.

    Returns:
        A single-element assistant-message list for the messages channel.
    """
    return [
        {
            "role": "assistant",
            "content": content,
            "metadata": {"phase": phase, **metadata},
        }
    ]
