"""Fold the finalize grounding pass's LLM telemetry into final metrics.

Split out of ``drain.py`` to keep it within the module-size budget; the
grounding pass's own ``scoped_telemetry`` call stays in ``drain.py``
(``_assess_claims``), which is the caller of the one function here.
"""

from __future__ import annotations

from typing import Any


def fold_grounding_telemetry(
    final_state: dict[str, Any], usage: dict[str, dict[str, Any]]
) -> None:
    """Fold the finalize grounding pass's LLM telemetry into final metrics.

    ``final_state["metrics"]`` is a plain (already-serialized) dict here,
    not the engine's live ``ExecutionMetrics`` object, so this round-trips
    through ``ExecutionMetrics.from_dict``/``to_dict`` around the same
    ``merge_metrics`` reducer every node commit uses, rather than
    reimplementing a dict-level merge. A no-op when the pass made no
    calls, so a fully-reused finalize pass never manufactures a metrics
    key.
    """
    if not usage:
        return
    from co_scientist.models import MetricDeltas
    from co_scientist.models_metrics import (
        ExecutionMetrics,
        create_metrics_update,
        merge_metrics,
    )

    calls = sum(entry.get("calls", 0) for entry in usage.values())
    existing = ExecutionMetrics.from_dict(final_state.get("metrics") or {})
    delta = create_metrics_update(
        deltas=MetricDeltas(llm_calls=calls), model_usage=usage
    )
    merged = merge_metrics(existing, delta)
    final_state["metrics"] = merged.to_dict()
