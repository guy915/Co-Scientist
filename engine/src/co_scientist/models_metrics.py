"""Execution-metrics models and node state-update helpers.

Split out of ``models`` to keep that module focused on the hypothesis
domain dataclasses; every name here remains importable from
``co_scientist.models`` via re-export shims, so import sites are
unaffected.
"""

import dataclasses
from dataclasses import dataclass, field
from typing import Any


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
    # a "metrics" key; "new" is that node's create_metrics_update(...)
    # output (deltas only, per its docstring), not a cumulative snapshot.
    # Create a NEW metrics object (don't mutate existing!)
    merged_phase_times = _merge_phase_times(
        existing.phase_times, new.phase_times
    )

    # Per-field merge policy, matched to what create_metrics_update
    # produces: hypothesis_count is the node's reported running *total*
    # rather than a delta, so max() keeps the larger observed count instead
    # of double-counting; total_time only overwrites when a node actually
    # measured one (> 0); the rest are straightforward additive deltas.
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
    )

    return merged


def create_metrics_update(
    hypothesis_count: int | None = None,
    reviews_count_delta: int = 0,
    tournaments_count_delta: int = 0,
    evolutions_count_delta: int = 0,
    llm_calls_delta: int = 0,
    total_time: float | None = None,
    phase_times: dict[str, float] | None = None,
) -> ExecutionMetrics:
    """Create new ExecutionMetrics with ONLY the deltas (not cumulative).

    The merge_metrics reducer will add these deltas to the existing state.
    Do NOT pass base metrics - only pass the increments from this node.

    Args:
        hypothesis_count: new total hypothesis count
            (replaces via max(), not adds)
        reviews_count_delta: number of reviews to add (delta only)
        tournaments_count_delta: number of tournaments to add (delta only)
        evolutions_count_delta: number of evolutions to add (delta only)
        llm_calls_delta: number of llm calls to add (delta only)
        total_time: new total time (only set if > 0)
        phase_times: new phase times dict (merged with existing)

    Returns:
        new ExecutionMetrics object with ONLY deltas
    """
    return ExecutionMetrics(
        hypothesis_count=hypothesis_count
        if hypothesis_count is not None
        else 0,
        reviews_count=reviews_count_delta,
        tournaments_count=tournaments_count_delta,
        evolutions_count=evolutions_count_delta,
        llm_calls=llm_calls_delta,
        total_time=total_time if total_time is not None else 0.0,
        phase_times=phase_times if phase_times is not None else {},
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
