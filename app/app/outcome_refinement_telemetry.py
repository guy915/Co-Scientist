"""Capture targeted evolution calls before its durable checkpoint."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from co_scientist.llm import scoped_telemetry
from co_scientist.models import MetricDeltas
from co_scientist.models_metrics import (
    ExecutionMetrics,
    create_metrics_update,
    merge_metrics,
)

from app import store
from app.engine_tasks_support import (
    _assert_task_commit_allowed,
    _metrics_snapshot,
)
from app.store import ScientificTask


@contextmanager
def capture_refinement_usage(state: dict[str, Any]) -> Iterator[None]:
    """Fold Robin calls into the existing metrics reducer."""
    with scoped_telemetry("outcome_refinement") as telemetry:
        try:
            yield
        finally:
            usage = telemetry.snapshot()
            if usage:
                current = state.get("metrics")
                if not isinstance(current, ExecutionMetrics):
                    current = ExecutionMetrics.from_dict(current or {})
                calls = sum(entry.get("calls", 0) for entry in usage.values())
                delta = create_metrics_update(
                    deltas=MetricDeltas(llm_calls=calls), model_usage=usage
                )
                state["metrics"] = merge_metrics(current, delta)


def restore_retry_usage(
    state: dict[str, Any], run_id: str, db_path: str | None
) -> None:
    """Use metrics persisted by earlier attempts beyond the last checkpoint."""
    persisted = store.get_run_metrics(run_id, db_path=db_path)
    if persisted is not None:
        state["metrics"] = ExecutionMetrics.from_dict(persisted)


def mark_retryable_with_usage(
    task: ScientificTask,
    action: dict[str, Any],
    state: dict[str, Any],
    db_path: str | None,
) -> None:
    """Keep a failed attempt's usage alongside its retryable action state."""
    with store.transaction(db_path) as conn:
        _assert_task_commit_allowed(task, conn)
        store.update_outcome_refinement_action(
            action["action_id"], status="retryable", conn=conn
        )
        store.save_run_metrics(task.run_id, _metrics_snapshot(state), conn=conn)
