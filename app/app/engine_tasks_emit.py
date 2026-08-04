"""Node-completion emitters for the durable engine-task modules.

The milestone/``scientific_task`` emitters every durable node commit
fires, plus the final-state shaping helper they share. Split from
``app.engine_tasks_support``, which re-exports these names so
``app.engine_tasks`` remains the stable import and monkeypatch surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.report_render import make_emitter


@dataclass(frozen=True)
class NodeCompletion:
    """One durable node commit's reportable facts.

    Attributes:
        node_name: Engine node whose result was committed.
        successor: Node the commit scheduled next, or ``None`` at the end.
        checkpoint_seq: Checkpoint sequence the commit produced.
    """

    node_name: str
    successor: str | None
    checkpoint_seq: int


def _plain_final_state(state: dict[str, Any]) -> dict[str, Any]:
    """Convert restored typed state into the app drain's persisted shape."""
    metrics = state.get("metrics")
    return {
        **state,
        "hypotheses": [item.to_dict() for item in state.get("hypotheses", [])],
        "articles": [item.to_dict() for item in state.get("articles") or []],
        "metrics": metrics.to_dict() if metrics else {},
    }


def _emit_node_milestone(
    run_id: str,
    node_name: str,
    state: dict[str, Any],
    db_path: str | None,
) -> None:
    """Append the milestone chat message for one completed node.

    Reuses ``events.py``'s canonical vocabulary and its
    ``append_node_milestone`` helper (the single home for the milestone
    message's shape) rather than carrying a second copy of the milestone
    strings. A no-op for node types with no milestone builder (e.g.
    ``review``, ``orchestrator``, ``safety_screen``,
    ``comprehensive_reflection``) -- checked before the state conversion
    below so those completions pay no extra cost.

    Callers place this immediately after the node's checkpoint commit (the
    same call site as the ``scientific_task`` event, where one exists), which
    is only reached once per real checkpoint advance -- a redelivered or
    replayed task returns earlier, at the function's existing idempotency
    guard, so a retried task never emits a duplicate milestone.
    A crash between the checkpoint commit and this call loses that node's
    milestone rather than duplicating it, the same failure mode the existing
    ``scientific_task`` emit already has.
    """
    from app.engine_adapter.events import (
        _MILESTONE_BUILDERS,
        _canonical_engine_payload,
        _canonical_event_type,
        append_node_milestone,
    )

    node_type = _canonical_event_type(node_name)
    if node_type not in _MILESTONE_BUILDERS:
        return
    payload = _canonical_engine_payload(
        node_name, node_type, _plain_final_state(state)
    )
    append_node_milestone(run_id, node_type, payload, db_path=db_path)


async def _emit_node_completion(
    run_id: str,
    completion: NodeCompletion,
    committed: dict[str, Any],
    db_path: str | None,
) -> None:
    """Emit the milestone and ``scientific_task`` event for one node.

    Pairs the two side-effects every node commit carries: a milestone chat
    message (a no-op for node types without one) and the ``scientific_task``
    completion event the frontend's live-activity feed (``ACTIVITY_META``)
    and mid-run refetch logic key on.

    Before this, the five fan-out aggregate completions (``generate``,
    ``review``, ``comprehensive_reflection``, ``deep_verification``,
    ``ranking`` -- the node types where the durable path's actual scientific
    work happens) emitted no event of any kind, leaving the live-activity feed
    blind to exactly the nodes doing the substantive work. Only the generic
    ``execute_node_task`` completion path emitted ``scientific_task``.

    Callers place this immediately after the node's checkpoint commit,
    downstream of that function's existing checkpoint-replay/supersession
    guard, so a redelivered or replayed task never double-emits either side
    effect (same reasoning as ``_emit_node_milestone``).

    Args:
        run_id: Run the committed node belongs to.
        completion: The node, its successor, and the committed checkpoint.
        committed: Workflow state the node's commit wrote.
        db_path: Optional override for the SQLite database path.
    """
    _emit_node_milestone(run_id, completion.node_name, committed, db_path)
    emit = make_emitter(run_id, db_path=db_path)
    await emit(
        "scientific_task",
        {
            "task": completion.node_name,
            "status": "completed",
            "checkpoint_seq": completion.checkpoint_seq,
            "successor": completion.successor,
        },
    )
