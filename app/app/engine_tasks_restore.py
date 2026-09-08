"""The state one durable node task starts from, and what it is told.

Split from ``app.engine_tasks_node`` at that module's 500-line ceiling.
What it owns is the difference between a checkpoint and the state a node
actually runs on: the checkpoint is the run's committed science, while
the overlays below are facts about *this* attempt -- steering waiting in
the durable queue, and how much of the task's retry budget is left.
Neither is checkpointed (``co_scientist.checkpoint``'s
``_TRANSIENT_CONTROL_KEYS``), because both describe the attempt rather
than the run.
"""

from __future__ import annotations

from typing import Any

from app.engine_tasks_inputs import _merge_scientist_inputs
from app.store import ScientificTask


def _restore_node_task_state(
    task: ScientificTask,
    checkpoint: dict[str, Any],
    generator: Any,
    opts: dict[str, Any],
    db_path: str | None,
) -> dict[str, Any]:
    """Restore workflow state and re-apply durable per-boundary overlays.

    Re-delivers durable scientist steering/private sources at every safe
    task boundary. ``_build_engine_opts`` only *reads* the message queue;
    the ids it read ride the commit target and are retired inside the
    transaction that commits this state's successor checkpoint, so a worker
    lost mid-node leaves the steer claimable rather than acknowledged.

    ``durable_retries_remain`` is the other overlay, and it is what lets a
    node whose synthesis is optional tell a recoverable failure from a
    final one (``co_scientist.agents.node_degradation``): a provider error
    with a retry behind it propagates so the worker re-runs the node,
    while the same error on the last attempt degrades the node rather than
    failing the task -- which, at the terminal node, settles the run and
    loses the report. The formula mirrors
    ``app.task_worker_outcomes._is_terminal_failure``, which mirrors
    ``app.store.tasks_attempts._persist_failed_attempt``'s own
    retry-left test; it assumes the failure is retryable, which holds
    because the two failures the worker refuses to retry
    (``TASK_CONTROL_FLOW_ERRORS``) never reach the degrade decision.
    """
    from co_scientist.checkpoint import restore_workflow_state

    state: dict[str, Any] = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    if opts.get("pending_steering"):
        state["pending_steering"] = True
    if opts.get("preferences"):
        state["preferences"] = opts["preferences"]
    if opts.get("context_enrichment_sources"):
        state["context_enrichment_sources"] = opts["context_enrichment_sources"]
    state["durable_retries_remain"] = task.attempt < task.max_attempts
    _merge_scientist_inputs(state, task.run_id, db_path)
    return state
