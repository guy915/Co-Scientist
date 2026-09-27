"""Capture targeted evolution calls before its durable checkpoint."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from co_scientist.llm_telemetry import scoped_telemetry

from app import store
from app.engine_adapter.drain_telemetry import fold_grounding_telemetry
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
            metrics = state.get("metrics")
            if metrics is not None and hasattr(metrics, "to_dict"):
                state["metrics"] = metrics.to_dict()
            fold_grounding_telemetry(state, telemetry.snapshot())


def restore_retry_usage(
    state: dict[str, Any], run_id: str, db_path: str | None
) -> None:
    """Use metrics persisted by earlier attempts beyond the last checkpoint."""
    persisted = store.get_run_metrics(run_id, db_path=db_path)
    if persisted is not None:
        state["metrics"] = persisted


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
