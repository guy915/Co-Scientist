"""Checkpoint guards for durable specialist-node tasks."""

from __future__ import annotations

from typing import Any

from app.engine_tasks_support import SupersededTaskError
from app.store import ScientificTask


def _check_node_task_checkpoint(
    task: ScientificTask, checkpoint: dict[str, Any], current_seq: int
) -> dict[str, Any] | None:
    """Return replay when committed; reject work behind another checkpoint.

    Portfolio rows validate against their named predecessor because a
    lookahead row cannot know its checkpoint sequence at enqueue time.
    """
    if checkpoint["stage"] == f"engine_task:{task.id}":
        return {"checkpoint_seq": current_seq, "replayed": True}
    if task.dependencies:
        _check_portfolio_predecessor(task, checkpoint)
        return None
    expected_seq = int(task.inputs.get("checkpoint_seq", -1))
    if current_seq > expected_seq:
        raise SupersededTaskError("specialist task checkpoint was superseded")
    if current_seq != expected_seq:
        raise RuntimeError("specialist task checkpoint does not match input")
    return None


def _check_portfolio_predecessor(
    task: ScientificTask, checkpoint: dict[str, Any]
) -> None:
    """Confirm the predecessor committed this task as its successor."""
    predecessor_id = task.dependencies[0]
    resume_successor = checkpoint.get("state", {}).get("resume_successor")
    stage = checkpoint["stage"]
    predecessor_stages = {
        f"engine_task:{predecessor_id}",
        f"engine_task_paused:{predecessor_id}",
    }
    if stage in predecessor_stages and resume_successor == task.task_type:
        return
    raise SupersededTaskError("portfolio task checkpoint was superseded")
