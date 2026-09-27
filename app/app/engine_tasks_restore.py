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

from app.engine_tasks_context import TaskCommit, _task_commit
from app.engine_tasks_inputs import _merge_scientist_inputs
from app.engine_tasks_support import (
    NODE_TASK_PREFIX,
    _durable_queue_snapshot,
    _generator_and_opts,
)
from app.store import ScientificTask

# The one boundary at which a scientist's hypothesis joins a running pool.
#
# The orchestrator is the run's only scheduling decision point, which makes
# it the only place a new competitor can appear without invalidating work
# already under way: never inside a ranking wave (where an idea joining
# mid-tournament carries an Elo nothing has played for), and never between
# a fan-out's items and its aggregate (which restores the checkpoint and
# would not find the hypothesis its item had just reviewed). It is also the
# node whose own commit checkpoints the enlarged pool, so every later task
# restores the newcomer from the checkpoint rather than re-merging it.
#
# What follows the admission is what keeps it from bypassing a gate: the
# admitted idea holds no *peer* review (its author's own review does not
# count as one -- ``co_scientist.models.has_peer_review``), so the
# scheduler's unreviewed-backlog transition (``scheduling/policy_checks``
# step 5) forces a review pass before the run may rank or evolve, and the
# cycle that follows carries it through safety_screen and the pre-ranking
# evidence gate like any generated idea.
#
# That backlog transition is only reached because the tournament's coverage
# floor is owed to peer-reviewed ideas alone
# (``ranking_lifecycle._coverage_floor``). The floor is checked *above* the
# backlog, so while it counted every rankable idea, a newcomer with no
# matches was itself a reason to rank, and the contribution entered the
# tournament ungated through the front door.
ADMISSION_NODE = "orchestrator"


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

    ``pending_steering`` is set on ``state`` only at the orchestrator: it
    is the sole node whose scheduling stats read that flag
    (``orchestrator_stats._build_scheduler_stats``), so setting it on
    every other node's restored state would do nothing but pretend a
    later commit consumed something it never acted on -- the actual
    consumption gate lives beside this one, in ``_task_commit``.

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
    from app.engine_adapter.checkpoints import restore_workflow_state

    state: dict[str, Any] = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    at_admission_node = (
        task.task_type.removeprefix(NODE_TASK_PREFIX) == ADMISSION_NODE
    )
    if opts.get("pending_steering") and at_admission_node:
        state["pending_steering"] = True
    if opts.get("preferences"):
        state["preferences"] = opts["preferences"]
    if opts.get("context_enrichment_sources"):
        state["context_enrichment_sources"] = opts["context_enrichment_sources"]
    state["durable_retries_remain"] = task.attempt < task.max_attempts
    _merge_scientist_inputs(
        state,
        task.run_id,
        db_path,
        admit_hypotheses=at_admission_node,
    )
    return state


def _prepare_node_task(
    task: ScientificTask,
    checkpoint: dict[str, Any],
    current_seq: int,
    db_path: str | None,
) -> tuple[dict[str, Any], TaskCommit, str]:
    """Restore this node's state and build its commit target.

    Only the orchestrator's own commit may acknowledge steering: it is
    the run's one scheduling decision point (see ``_task_commit``).
    """
    generator, opts = _generator_and_opts(task, db_path)
    state = _restore_node_task_state(task, checkpoint, generator, opts, db_path)
    node_name = task.task_type.removeprefix(NODE_TASK_PREFIX)
    if node_name == "orchestrator":
        state["durable_task_queue"] = _durable_queue_snapshot(
            task.run_id, db_path
        )
    commit = _task_commit(
        task,
        current_seq,
        db_path,
        opts,
        consume_steering=(node_name == ADMISSION_NODE),
    )
    return state, commit, node_name
