"""The metrics snapshot a durable task commit persists.

Split out of ``engine_tasks.support`` to keep that module on the task
vocabulary and checkpoint plumbing; the names callers use stay importable
from ``app.engine_tasks.support`` via re-export, so existing import sites and
monkeypatch seams are unaffected.

The snapshot is what makes a run's metrics readable while it is still
running (finding L14). It is built at a commit boundary and written inside
the transaction that commit already holds open -- never on a timer and
never per LLM call, because a write stream of that shape starves SQLite's
single writer.
"""

from __future__ import annotations

from typing import Any


def _performance_assessment(state: dict[str, Any]) -> dict[str, Any] | None:
    """Return the Supervisor's per-agent performance assessment, if any.

    Written once, during planning, into
    ``state["supervisor_guidance"]["performance_assessment"]``;
    ``supervisor_guidance`` carries no reducer (see
    ``task_runtime.channel_reducers``) so it is last-write-wins and no
    later node touches it, meaning it stays present in state for the rest
    of the run once planning has committed. Finding F5: this was computed
    and never read by anything -- persisting it here makes it inspectable
    (via the same metrics row and endpoint) without building the
    weighted-sampling allocator that would consume it, which is Stage 11
    and explicitly out of scope.

    Args:
        state: The workflow state at a commit boundary.

    Returns:
        The assessment dict, or None when planning has not produced one.
    """
    guidance = state.get("supervisor_guidance")
    if not isinstance(guidance, dict):
        return None
    assessment = guidance.get("performance_assessment")
    return assessment if isinstance(assessment, dict) and assessment else None


def _plain_metrics(state: dict[str, Any]) -> dict[str, Any]:
    """Return ``state["metrics"]`` as a plain dict, or ``{}`` if absent."""
    metrics = state.get("metrics")
    if metrics is None:
        return {}
    if hasattr(metrics, "to_dict"):
        return dict(metrics.to_dict())
    return dict(metrics)


def _metrics_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    """Return the run's accumulated metrics as a plain JSON-safe dict.

    At a node-commit boundary ``state["metrics"]`` is the engine's live
    ``ExecutionMetrics`` object -- ``apply_task_update`` has already
    merged this node's delta into the running total (finding L3's
    ``llm_calls`` deltas included) -- so ``to_dict()`` is the same
    conversion ``checkpoint.serialize_workflow_state`` uses. Absent or
    already-plain metrics degrade to ``{}``/a shallow copy rather than
    raising, since a metrics write must never be why a node commit fails.

    Also folds in the Supervisor's ``performance_assessment`` (finding
    F5) once planning has produced one, so both land in the run's single
    metrics row rather than needing a second persisted artifact.

    Args:
        state: The workflow state at a commit boundary.

    Returns:
        A JSON-safe dict of the run's accumulated metrics.
    """
    snapshot = _plain_metrics(state)
    assessment = _performance_assessment(state)
    if assessment is not None:
        snapshot["performance_assessment"] = assessment
    return snapshot
