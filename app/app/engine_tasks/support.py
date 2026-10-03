"""Shared plumbing for the durable engine-task modules."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import app.engine_tasks.runtime as engine_tasks_runtime
import app.store as store
from app.engine_adapter.opts import (
    CONSUMED_STEERING_IDS_OPT,
    build_engine_opts,
    build_generator,
)
from app.engine_tasks.portfolio import _enqueue_node_portfolio
from app.run_events import make_emitter
from app.run_modes import resolved_run_config
from app.store import ScientificTask


@dataclass(frozen=True)
class TaskCommit:
    """One durable task's commit target.

    Every commit helper needs the same three values -- the leased task, the
    checkpoint sequence it was scheduled against, and the optional database
    override -- so they travel together rather than being re-declared on
    each signature.

    Attributes:
        task: The leased scientific task being committed.
        current_seq: Checkpoint sequence the task was scheduled against.
        db_path: Optional override for the SQLite database path.
        steering_ids: Steering messages this commit acknowledges. Only the
            orchestrator's own node commit ever carries these (see
            ``_task_commit``'s ``consume_steering``): the orchestrator is
            the run's one scheduling decision point, and every other node
            merely restarts from a checkpoint that never held the pending
            flag, so a task other than the orchestrator's has nothing of
            its own to acknowledge. Acknowledged inside the checkpoint
            transaction, never before it, so a crash mid-task leaves the
            steer claimable rather than applied to nothing.
    """

    task: ScientificTask
    current_seq: int
    db_path: str | None
    steering_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class ExactSuccessor:
    """The non-node task an exact-checkpoint commit enqueues next.

    Attributes:
        task_type: Durable task type to enqueue.
        inputs: Scheduling inputs, merged with the committed checkpoint seq.
        idempotency_key: Key template formatted with ``checkpoint_seq``; its
            ``{task_type}:{checkpoint_seq}`` shape is what makes redelivery
            a no-op, so it is never derived from anything else.
    """

    task_type: str
    inputs: dict[str, Any]
    idempotency_key: str


def _task_commit(
    task: ScientificTask,
    current_seq: int,
    db_path: str | None,
    opts: dict[str, Any],
    *,
    consume_steering: bool = False,
) -> TaskCommit:
    """Bind a task's commit target to the steering its opts folded in.

    ``consume_steering`` must be explicit at every call site (default
    False, so a caller that forgets it simply defers the steer rather than
    acknowledging it out from under the orchestrator -- the safe
    direction). Only the orchestrator's own node commit passes True: it is
    the run's one scheduling decision point (``SchedulerStats.
    pending_steering`` is read nowhere else), so acknowledging anywhere
    else retires a steer before the decision it was meant to influence
    ever runs. Bootstrap opts also carry the flag (any steering queued
    before the run started) but no longer consume it here either -- it
    stays pending until the run's first orchestrator cycle, the same
    boundary a message queued mid-run waits for.
    """
    if not consume_steering:
        return TaskCommit(task, current_seq, db_path, ())
    consumed = opts.get(CONSUMED_STEERING_IDS_OPT) or []
    return TaskCommit(
        task, current_seq, db_path, tuple(int(item) for item in consumed)
    )


def _ack_consumed_steering(
    commit: TaskCommit, conn: sqlite3.Connection, state: dict[str, Any]
) -> None:
    """Retire the steering this commit's state carries, in its transaction.

    Called from inside every checkpoint transaction rather than where the
    guidance was read: the acknowledgement and the state that honors it
    have to land or roll back together, or a worker lost between them
    retires a steer the run never acted on.

    ``state["next_task"]`` -- present once the orchestrator has actually
    decided, absent (or stale, from before this cycle) if the run was
    paused ahead of that decision -- rides along as the "how it changed
    the plan" record on the message row. No-op when nothing is being
    acknowledged (``commit.steering_ids`` empty), so a caller with nothing
    fresh to report never overwrites anything.
    """
    store.mark_steering_applied(
        list(commit.steering_ids), conn=conn, decision=state.get("next_task")
    )


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


def merge_usage_snapshots(
    snapshots: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Fold per-item ``llm.telemetry`` snapshots into one usage dict.

    Args:
        snapshots: One ``TelemetryAccumulator.snapshot()`` per fan-out item
            or ranking wave, in any order; empty snapshots are skipped.

    Returns:
        The combined per-(phase, model) usage, additive across snapshots --
        the same rule ``models.metrics.merge_metrics`` applies to a node's
        own ``model_usage`` delta.
    """
    from co_scientist.models import (
        ExecutionMetrics,
        create_metrics_update,
        merge_metrics,
    )

    merged = ExecutionMetrics()
    for snapshot in snapshots:
        if not snapshot:
            continue
        merged = merge_metrics(
            merged, create_metrics_update(model_usage=dict(snapshot))
        )
    # The app's mypy config skips following ``co_scientist`` imports, so
    # ``merged.model_usage`` arrives here as ``Any``; restate the engine's
    # declared field type on the return rather than passing it on unchecked.
    usage: dict[str, dict[str, Any]] = merged.model_usage
    return usage


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


def _save_paused_checkpoint(
    commit: TaskCommit,
    state: dict[str, Any],
    resume_successor: str,
    envelope: dict[str, Any],
    conn: sqlite3.Connection,
) -> int:
    """Save paused state inside the task's already-open commit transaction."""
    from co_scientist.checkpoint import CHECKPOINT_VERSION

    pass
    pass

    task = commit.task
    latest = store.get_latest_checkpoint(task.run_id, conn=conn)
    latest_seq = int(latest["seq"]) if latest else 0
    if latest_seq != commit.current_seq:
        raise RuntimeError("checkpoint changed while pausing task")
    _ack_consumed_steering(commit, conn, state)
    store.save_run_metrics(task.run_id, _metrics_snapshot(state), conn=conn)
    return store.save_checkpoint(
        task.run_id,
        store.NewCheckpoint(
            stage=f"engine_task_paused:{task.id}",
            schema_version=CHECKPOINT_VERSION,
            last_event_seq=envelope["last_event_seq"],
            state={
                "provider": _CHECKPOINT_PROVIDER,
                "resume_successor": resume_successor,
                **envelope,
            },
        ),
        conn=conn,
    )


def _save_paused_if_requested(
    commit: TaskCommit,
    state: dict[str, Any],
    resume_successor: str,
    envelope: dict[str, Any],
    conn: sqlite3.Connection,
) -> tuple[int, None] | None:
    """Persist the result as paused state when the run is already paused."""
    task = commit.task
    run = conn.execute(
        "SELECT status FROM runs WHERE id=?", (task.run_id,)
    ).fetchone()
    if run is None or run["status"] != store.RunStatus.PAUSED.value:
        return None
    envelope["last_event_seq"] = store.latest_event_seq(task.run_id, conn=conn)
    return (
        _save_paused_checkpoint(
            commit, state, resume_successor, envelope, conn
        ),
        None,
    )


def _save_paused_state(
    commit: TaskCommit,
    state: dict[str, Any],
    resume_successor: str,
) -> int:
    """Checkpoint an in-flight task without making successor work claimable.

    A pause commits the guidance-carrying state as durably as a successor
    commit does, so it retires the same steering in the same transaction.
    """
    from co_scientist.checkpoint import serialize_workflow_state

    pass

    task, db_path = commit.task, commit.db_path
    envelope = serialize_workflow_state(
        state,
        last_event_seq=store.latest_event_seq(task.run_id, db_path=db_path),
    )
    with store.transaction(db_path) as conn:
        assert_task_commit_allowed(task, conn)
        envelope["last_event_seq"] = store.latest_event_seq(
            task.run_id, conn=conn
        )
        return _save_paused_checkpoint(
            commit, state, resume_successor, envelope, conn
        )


def _save_paused_state_if_requested(
    commit: TaskCommit,
    state: dict[str, Any],
    resume_successor: str,
) -> int | None:
    """Serialize outside the lock, then atomically check pause and save."""
    from co_scientist.checkpoint import serialize_workflow_state

    pass

    task, db_path = commit.task, commit.db_path
    envelope = serialize_workflow_state(state, last_event_seq=0)
    with store.transaction(db_path) as conn:
        assert_task_commit_allowed(task, conn)
        paused = _save_paused_if_requested(
            commit, state, resume_successor, envelope, conn
        )
        return paused[0] if paused is not None else None


def _pause_node_task_if_requested(
    commit: TaskCommit,
    run: store.RunRow,
    node_name: str,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    """Checkpoint and pause a node task the operator paused mid-flight.

    Args:
        commit: The leased task, its expected checkpoint seq, and db path.
        run: The task's run row, read for a mid-flight pause.
        node_name: Engine node the paused task was about to run.
        state: Workflow state to checkpoint at the pause point.

    Returns:
        The pause result to return, or ``None`` if the run is not paused.
    """
    if run.status != store.RunStatus.PAUSED.value:
        return None
    checkpoint_seq = _save_paused_state(commit, state, commit.task.task_type)
    return {
        "checkpoint_seq": checkpoint_seq,
        "node": node_name,
        "status": "paused",
    }


# Every durable task type in the engine-workflow family shares this
# prefix (bootstrap, node dispatch, finalize, fan-out, ranking) as
# opposed to unrelated task types like "notification.email". Callers
# that only need "does this run still have engine work" (the run
# lifecycle router, the standalone worker) match against this rather
# than the fine-grained task types below.
ENGINE_TASK_PREFIX = "engine."
_CHECKPOINT_PROVIDER = "engine"
BOOTSTRAP_TASK = "engine.bootstrap"
NODE_TASK_PREFIX = "engine.node."
FINALIZE_TASK = "engine.finalize"
REVIEW_ITEM_TASK = "engine.fanout.review.item"
REVIEW_AGGREGATE_TASK = "engine.fanout.review.aggregate"
VERIFICATION_ITEM_TASK = "engine.fanout.verification.item"
VERIFICATION_AGGREGATE_TASK = "engine.fanout.verification.aggregate"
RANKING_MATCH_TASK = "engine.ranking.match"
RANKING_FINALIZE_TASK = "engine.ranking.finalize"
# Emit tournament progress every Nth match rather than once per match. A match
# is its own durable task taking roughly a minute, so a full tournament runs
# for tens of minutes; without this it committed real work the whole time and
# emitted nothing, leaving the live-activity feed showing a healthy run as
# frozen. Per-match events would fix the silence but flood the feed, which
# renders only the newest handful of events and would lose every other phase.
RANKING_PROGRESS_EVERY = 5
GENERATION_STRATEGY_TASK = "engine.fanout.generation.strategy"
GENERATION_AGGREGATE_TASK = "engine.fanout.generation.aggregate"
MATURE_REFLECTION_ITEM_TASK = "engine.fanout.reflection.item"
MATURE_REFLECTION_AGGREGATE_TASK = "engine.fanout.reflection.aggregate"
OUTCOME_REFINEMENT_TASK = "engine.outcome.refinement"


class SupersededTaskError(RuntimeError):
    """Signals that a newer checkpoint made a leased task obsolete."""


class SafetyHoldError(RuntimeError):
    """Signals that a safety gate held the run pending human adjudication.

    Neither a failure nor a completion. The gate did its job, so retrying
    the task cannot change the outcome -- only a reviewer can -- but the
    boundary's work is not done either, and recording it as succeeded is
    what left an approved hold with nothing to claim (a succeeded row is
    never revived, and its idempotency key cannot change while the run
    makes no progress). The worker parks the task instead; approving the
    hold releases it through the ordinary resume path.
    """


def _require_run(task: ScientificTask, db_path: str | None) -> store.RunRow:
    """Return the task's run or raise if it has been deleted."""
    run = store.get_run(task.run_id, db_path=db_path)
    if run is None:
        raise RuntimeError(f"run {task.run_id} no longer exists")
    return run


def _require_item_task(
    item_id: Any, db_path: str | None, *, kind: str
) -> ScientificTask:
    """Return a fan-out item task or raise if it has vanished mid-flight."""
    item = store.get_task(str(item_id), db_path=db_path)
    if item is None:
        raise RuntimeError(f"{kind} {item_id} disappeared")
    return item


def _successor_task_type(successor: str | None) -> str:
    """Map a node successor to its durable task type (finalize when None)."""
    if successor is None:
        return FINALIZE_TASK
    return f"{NODE_TASK_PREFIX}{successor}"


def assert_task_commit_allowed(
    task: ScientificTask, conn: sqlite3.Connection
) -> None:
    """Require the task's lease and run to remain live inside its commit."""
    row = conn.execute(
        "SELECT task.status AS task_status, task.lease_owner AS lease_owner, "
        "task.attempt AS attempt, "
        "run.status AS run_status FROM scientific_tasks AS task "
        "JOIN runs AS run ON run.id=task.run_id "
        "WHERE task.id=? AND task.run_id=?",
        (task.id, task.run_id),
    ).fetchone()
    terminal = {status.value for status in store.TERMINAL_STATUSES}
    if (
        task.status != "leased"
        or task.lease_owner is None
        or row is None
        or row["task_status"] != "leased"
        or row["lease_owner"] != task.lease_owner
        or row["attempt"] != task.attempt
        or row["run_status"] in terminal
    ):
        # Import lazily to keep the shared support module below the worker
        # outcome module in the import graph. BEGIN IMMEDIATE makes this
        # read indivisible with the checkpoint and successor writes below.
        from app.task_worker.outcomes import _LeaseLostError

        raise _LeaseLostError(
            f"task {task.id} cannot commit after lease revocation "
            "or run termination"
        )


def _generator_and_opts(
    task: ScientificTask, db_path: str | None
) -> tuple[Any, dict[str, Any]]:
    from co_scientist import HypothesisGenerator

    from app.credentials import get_run_credential

    run = _require_run(task, db_path)
    cfg = resolved_run_config(run.config)
    generator = build_generator(
        HypothesisGenerator,
        cfg,
        offline=store.run_used_offline(run),
        byok=get_run_credential(task.run_id, db_path=db_path),
    )
    return generator, build_engine_opts(cfg, run.id, db_path)


def _generator_for_restore(task: ScientificTask, db_path: str | None) -> Any:
    """Build a registry-compatible generator without consuming steering."""
    from co_scientist import HypothesisGenerator

    from app.credentials import get_run_credential

    run = _require_run(task, db_path)
    return build_generator(
        HypothesisGenerator,
        resolved_run_config(run.config),
        offline=store.run_used_offline(run),
        byok=get_run_credential(task.run_id, db_path=db_path),
    )


def _save_node_checkpoint(
    task: ScientificTask,
    envelope: dict[str, Any],
    successor_type: str,
    expected_checkpoint_seq: int,
    conn: sqlite3.Connection,
) -> int:
    """Commit one node's checkpoint inside the caller's transaction.

    ``resume_successor`` names the task that this checkpoint's committed
    state feeds into next, so a crash-resume re-enqueues the right node
    rather than the orchestrator default in
    ``task_worker.enqueue_run_workflow``. Its own resume-side enqueue
    derives the same predecessor-anchored idempotency key
    (``app.engine_tasks.portfolio``) from this checkpoint's ``stage``, so
    resume resolves to the exact already-queued task instead of creating
    a second one. Without it, a run interrupted right after bootstrap
    resumed at the orchestrator with no supervisor_guidance in state and
    failed in generation. The cooperative-pause path
    (``_save_paused_state``) already records this; this closes that gap.
    """
    from co_scientist.checkpoint import CHECKPOINT_VERSION

    latest = store.get_latest_checkpoint(task.run_id, conn=conn)
    latest_seq = int(latest["seq"]) if latest else 0
    if latest_seq != expected_checkpoint_seq:
        raise RuntimeError(
            "checkpoint changed while scientific task was executing"
        )
    return store.save_checkpoint(
        task.run_id,
        store.NewCheckpoint(
            stage=f"engine_task:{task.id}",
            schema_version=CHECKPOINT_VERSION,
            last_event_seq=envelope["last_event_seq"],
            state={
                "provider": _CHECKPOINT_PROVIDER,
                "resume_successor": successor_type,
                **envelope,
            },
        ),
        conn=conn,
    )


def _save_state_and_enqueue(
    commit: TaskCommit,
    state: dict[str, Any],
    successor: str | None,
    *,
    pause_if_requested: bool = False,
) -> tuple[int, str | None]:
    """Atomically checkpoint one node effect and enqueue its successor.

    Also persists the run's accumulated metrics snapshot in the same
    transaction (finding L14): every node-level, ranking-chain, and
    fan-out-aggregate commit routes through this one function, so a
    single hook here gives a running run's ``GET /api/runs/{id}/metrics``
    live numbers without a second transaction or a poll-driven write.

    The successor enqueue (``app.engine_tasks.portfolio``) also chains
    however much further of the deterministic node run
    ``co_scientist.task_runtime.plan_portfolio`` can already resolve from
    ``state`` (finding F4): a bounded portfolio rather than one task at a
    time, without changing that this transaction still advances the
    checkpoint chain by exactly one commit. Node commits set
    ``pause_if_requested`` to choose a paused checkpoint under this same
    transaction when the API pause has already committed.
    """
    from co_scientist.checkpoint import serialize_workflow_state

    task, db_path = commit.task, commit.db_path
    envelope = serialize_workflow_state(
        state,
        last_event_seq=store.latest_event_seq(task.run_id, db_path=db_path),
    )
    successor_type = _successor_task_type(successor)
    with store.transaction(db_path) as conn:
        assert_task_commit_allowed(task, conn)
        if pause_if_requested:
            paused = _save_paused_if_requested(
                commit, state, successor_type, envelope, conn
            )
            if paused is not None:
                return paused
        checkpoint_seq = _save_node_checkpoint(
            task, envelope, successor_type, commit.current_seq, conn
        )
        successor_task = _enqueue_node_portfolio(
            task, state, successor, successor_type, conn
        )
        _ack_consumed_steering(commit, conn, state)
        store.save_run_metrics(task.run_id, _metrics_snapshot(state), conn=conn)
    return checkpoint_seq, successor_task.id


def _save_exact_checkpoint(
    task: ScientificTask,
    envelope: dict[str, Any],
    expected_checkpoint_seq: int,
    conn: sqlite3.Connection,
    *,
    changed_message: str = "checkpoint changed during scientific task",
) -> int:
    """Commit one checkpoint for a non-node scientific task."""
    from co_scientist.checkpoint import CHECKPOINT_VERSION

    latest = store.get_latest_checkpoint(task.run_id, conn=conn)
    latest_seq = int(latest["seq"]) if latest else 0
    if latest_seq != expected_checkpoint_seq:
        raise RuntimeError(changed_message)
    return store.save_checkpoint(
        task.run_id,
        store.NewCheckpoint(
            stage=f"engine_task:{task.id}",
            schema_version=CHECKPOINT_VERSION,
            last_event_seq=envelope["last_event_seq"],
            state={"provider": _CHECKPOINT_PROVIDER, **envelope},
        ),
        conn=conn,
    )


def _enqueue_exact_successor(
    task: ScientificTask,
    successor: ExactSuccessor,
    checkpoint_seq: int,
    conn: sqlite3.Connection,
) -> ScientificTask:
    """Enqueue a non-node scientific task at an exact checkpoint sequence."""
    inputs = {**successor.inputs, "checkpoint_seq": checkpoint_seq}
    return store.enqueue_task(
        store.NewTask(
            run_id=task.run_id,
            task_type=successor.task_type,
            inputs=inputs,
            idempotency_key=successor.idempotency_key.format(
                checkpoint_seq=checkpoint_seq
            ),
            priority=86,
            dependencies=(task.id,),
            provenance={"scheduled_by": task.task_type},
        ),
        conn=conn,
    )


def _save_state_and_enqueue_exact(
    commit: TaskCommit,
    state: dict[str, Any],
    successor: ExactSuccessor,
) -> tuple[int, str]:
    """Checkpoint one effect and enqueue a non-node scientific task.

    Args:
        commit: The leased task, its expected checkpoint seq, and db path.
        state: Workflow state to serialize into the checkpoint.
        successor: The non-node task to enqueue against the new checkpoint.

    Returns:
        A tuple of (committed checkpoint sequence, successor task id).
    """
    from co_scientist.checkpoint import serialize_workflow_state

    task = commit.task
    envelope = serialize_workflow_state(
        state,
        last_event_seq=store.latest_event_seq(
            task.run_id, db_path=commit.db_path
        ),
    )
    with store.transaction(commit.db_path) as conn:
        assert_task_commit_allowed(task, conn)
        checkpoint_seq = _save_exact_checkpoint(
            task, envelope, commit.current_seq, conn
        )
        enqueued = _enqueue_exact_successor(
            task, successor, checkpoint_seq, conn
        )
    return checkpoint_seq, enqueued.id


def _latest_task_checkpoint(
    task: ScientificTask, db_path: str | None
) -> tuple[dict[str, Any], int]:
    checkpoint = store.get_latest_checkpoint(task.run_id, db_path=db_path)
    if checkpoint is None:
        raise RuntimeError("specialist task has no workflow checkpoint")
    return checkpoint, int(checkpoint["seq"])


def _replay_or_supersede(
    task: ScientificTask,
    db_path: str | None,
    *,
    label: str,
) -> tuple[dict[str, Any] | None, dict[str, Any], int]:
    """Guard a leased task against replay or a superseding checkpoint.

    Shared by every scientific-task executor that expects to run against an
    exact checkpoint sequence (ranking match/finalize, and the review,
    generation, mature-reflection, and verification aggregates). Returns a
    ``(replay_result, checkpoint, current_seq)`` tuple: if ``replay_result``
    is not ``None``, the caller must return it immediately -- this task
    already committed the checkpoint now on record. Otherwise
    ``checkpoint``/``current_seq`` are the task's own checkpoint to restore
    state from. Raises ``SupersededTaskError`` when a different task
    advanced the checkpoint first.
    """
    checkpoint, current_seq = _latest_task_checkpoint(task, db_path)
    expected_seq = int(task.inputs["checkpoint_seq"])
    if (
        current_seq > expected_seq
        and checkpoint["stage"] == f"engine_task:{task.id}"
    ):
        return (
            {"checkpoint_seq": current_seq, "replayed": True},
            checkpoint,
            current_seq,
        )
    if current_seq != expected_seq:
        raise SupersededTaskError(f"{label} checkpoint was superseded")
    return None, checkpoint, current_seq


def restore_checkpoint_state(
    task: ScientificTask, checkpoint: dict[str, Any], db_path: str | None
) -> dict[str, Any]:
    """Rebuild the workflow state ``checkpoint`` holds for a leased task.

    The generator exists only to hand its tool registry to the restore, so it
    is built per call and dropped: nothing it creates outlives the calling
    cohort's event loop, and steering is not consumed.
    """
    from app.engine_adapter import restore_workflow_state

    generator = engine_tasks_runtime.active().generator_for_restore(
        task, db_path
    )
    return restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )


def leased_state(
    task: ScientificTask, db_path: str | None, *, label: str
) -> tuple[dict[str, Any] | None, dict[str, Any], int]:
    """Guard a leased task against replay or supersession, then restore state.

    Returns ``(replay_result, state, current_seq)``. When ``replay_result`` is
    not ``None`` the caller returns it at once and ``state`` is empty: this
    task already committed the checkpoint now on record. Raises
    ``SupersededTaskError`` exactly as ``_replay_or_supersede`` does.
    """
    replay, checkpoint, current_seq = _replay_or_supersede(
        task, db_path, label=label
    )
    if replay is not None:
        return replay, {}, current_seq
    return (
        None,
        restore_checkpoint_state(task, checkpoint, db_path),
        current_seq,
    )


def _restore_item_checkpoint(
    task: ScientificTask, db_path: str | None, *, superseded: str
) -> tuple[dict[str, Any], int]:
    """Restore the read-only workflow state a fan-out item task runs against.

    Rejects a task whose leased checkpoint a newer one has already replaced,
    then rebuilds the immutable state from the current checkpoint.

    Args:
        task: The leased fan-out item task.
        db_path: Optional override for the SQLite database path.
        superseded: Item label for the ``SupersededTaskError`` message.

    Returns:
        The restored workflow state dict and the leased checkpoint sequence.

    Raises:
        SupersededTaskError: When the leased checkpoint was superseded.
    """
    checkpoint, current_seq = _latest_task_checkpoint(task, db_path)
    expected_seq = int(task.inputs["checkpoint_seq"])
    if current_seq != expected_seq:
        raise SupersededTaskError(f"{superseded} checkpoint was superseded")
    return restore_checkpoint_state(task, checkpoint, db_path), expected_seq
