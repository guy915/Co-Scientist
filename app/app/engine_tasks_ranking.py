"""Durable tournament execution: sequential ranking-match waves.

Schedules the ranking chain from a committed checkpoint, judges bounded
waves of Elo matchups (one durable task per wave), and finalizes the
tournament back into orchestration. Split from ``app.engine_tasks``,
which re-exports these names for compatibility. Wave construction and
judging moved on to ``app.engine_tasks_ranking_wave``; every moved name is
re-exported below so this module's namespace keeps resolving.
"""

from __future__ import annotations

from typing import Any

from app import store
from app.engine_tasks_context import ExactSuccessor, TaskCommit
from app.engine_tasks_ranking_wave import (
    RANKING_WAVE_SIZE as RANKING_WAVE_SIZE,
)
from app.engine_tasks_ranking_wave import (
    _advance_ranking_wave,
    _prepare_ranking_wave,
    _WavePlan,
    _WaveResult,
)
from app.engine_tasks_ranking_wave import (
    _apply_wave_elo as _apply_wave_elo,
)
from app.engine_tasks_ranking_wave import (
    _judge_one_matchup as _judge_one_matchup,
)
from app.engine_tasks_ranking_wave import (
    _judge_wave_matchups as _judge_wave_matchups,
)
from app.engine_tasks_ranking_wave import (
    _ranking_wave as _ranking_wave,
)
from app.engine_tasks_ranking_wave import (
    _WaveJudgeContext as _WaveJudgeContext,
)
from app.engine_tasks_support import (
    RANKING_FINALIZE_TASK,
    RANKING_MATCH_TASK,
    RANKING_PROGRESS_EVERY,
    NodeCompletion,
    _emit_node_completion,
    _generator_for_restore,
    _replay_or_supersede,
    _save_state_and_enqueue,
    _save_state_and_enqueue_exact,
)
from app.store import ScientificTask
from app.store.runs_reconcile import _ACTIVE_RUN_STATUSES


def _ranking_eligible(state: dict[str, Any]) -> list[Any]:
    """Return hypotheses eligible for a tournament under engine policy.

    Ideas the pre-ranking evidence gate quarantined (``evidence_blocked``) are
    excluded alongside deep-verification-undermined and review-rejected ideas,
    so an unsupported or contradicted claim never influences the decisive Elo
    tournament even though the report gate would later drop it. The predicate
    lives on ``Hypothesis.is_rankable`` so the durable path and the engine
    scheduler's coverage accounting stay in sync (a mismatch loops the
    orchestrator on ranking).

    Also requires ``has_peer_review``, mirroring the coverage floor's own
    filter (``ranking_lifecycle._coverage_floor``). In the ordinary cycle
    this changes nothing: the scheduler's unreviewed-backlog check forces a
    review before RANK is ever scheduled, so nothing unreviewed reaches
    here. It matters for a scientist hypothesis admitted on the very cycle
    the orchestrator retries a *failed* RANK (``policy_checks._check_retry``
    sits above the review-backlog check), which would otherwise hand a
    newcomer holding no peer review real tournament matches -- passing no
    gate at all (HITL-MANUAL-HYP-001). Safe against the sync warning above:
    the backlog check still counts an unreviewed idea via
    ``has_peer_review`` regardless of this filter, so it is caught and
    reviewed once the (bounded) retry window closes.
    """
    from co_scientist.models import has_peer_review

    return [
        hypothesis
        for hypothesis in state["hypotheses"]
        if hypothesis.is_rankable() and has_peer_review(hypothesis)
    ]


def _ranking_chain_skipped(state: dict[str, Any], eligible: list[Any]) -> bool:
    """Report whether this cycle must not schedule a tournament at all.

    Args:
        state: Workflow state the tournament would be scheduled from.
        eligible: Hypotheses allowed into the tournament this cycle.

    Returns:
        True when there is nothing to judge, or no round budget left.
    """
    from co_scientist.agents.ranking.ranking_lifecycle import (
        _tournament_round_count,
    )

    if len(eligible) < 2:
        return True
    # The app's mypy config skips following ``co_scientist`` imports, so the
    # engine's declared ``-> int`` arrives here as ``Any``. Restate it on the
    # binding rather than returning an unchecked comparison.
    rounds_left: int = _tournament_round_count(state, state["hypotheses"])
    # tournament_pairs is a whole-run budget and the scheduler asks for
    # ranking once per cycle, so this is the common case late in a run.
    # Scheduling anyway would not merely waste a task: the tournament
    # clears pending_ranking_matchups on entry, so an empty one overwrites
    # the matches the run already judged.
    return rounds_left < 1


def _enqueue_first_ranking_match(
    task: ScientificTask,
    state: dict[str, Any],
    checkpoint_seq: int,
    rounds: int,
    db_path: str | None,
) -> tuple[int, str]:
    """Checkpoint the prepared tournament and enqueue its first match.

    Args:
        task: The ranking node task scheduling the chain.
        state: Workflow state carrying the prepared tournament.
        checkpoint_seq: Checkpoint sequence the chain was prepared against.
        rounds: Number of matches the tournament will judge.
        db_path: Optional override for the SQLite database path.

    Returns:
        The committed checkpoint sequence and the first match task's id.
    """
    return _save_state_and_enqueue_exact(
        TaskCommit(task, checkpoint_seq, db_path),
        state,
        ExactSuccessor(
            task_type=RANKING_MATCH_TASK,
            inputs={
                "round_index": 0,
                "tournament_rounds": rounds,
                "total_llm_calls": 0,
                "previous_pair": [],
                "model_usage": {},
            },
            idempotency_key="ranking:match:{checkpoint_seq}:0",
        ),
    )


async def _schedule_ranking_chain(
    task: ScientificTask,
    state: dict[str, Any],
    checkpoint_seq: int,
    *,
    db_path: str | None,
) -> dict[str, Any] | None:
    """Prepare a tournament and schedule its first sequential match task."""
    from co_scientist.agents.ranking.ranking import _prepare_ranking_round

    eligible = _ranking_eligible(state)
    if _ranking_chain_skipped(state, eligible):
        return None
    rounds, *_ = await _prepare_ranking_round(state, eligible)
    state["pending_ranking_matchups"] = []
    committed_seq, successor_id = _enqueue_first_ranking_match(
        task, state, checkpoint_seq, rounds, db_path
    )
    return {
        "checkpoint_seq": committed_seq,
        "successor_task_id": successor_id,
        "tournament_rounds": rounds,
        "node": "ranking",
    }


def _restore_ranking_state(
    task: ScientificTask, db_path: str | None, *, label: str
) -> tuple[dict[str, Any] | None, dict[str, Any], int]:
    """Guard a ranking task against replay/supersession, then restore state."""
    from app.engine_adapter.checkpoints import restore_workflow_state

    replay, checkpoint, current_seq = _replay_or_supersede(
        task, db_path, label=label
    )
    if replay is not None:
        return replay, {}, current_seq
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    return None, state, current_seq


def _ranking_match_successor(
    next_index: int,
    rounds: int,
    total_calls: int,
    last_pair: list[str],
    model_usage: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """Return the next ranking task type and its scheduling inputs."""
    if next_index < rounds:
        return RANKING_MATCH_TASK, {
            "round_index": next_index,
            "tournament_rounds": rounds,
            "total_llm_calls": total_calls,
            "previous_pair": last_pair,
            "model_usage": model_usage,
        }
    return RANKING_FINALIZE_TASK, {
        "tournament_rounds": rounds,
        "total_llm_calls": total_calls,
        "model_usage": model_usage,
    }


async def _emit_ranking_wave_progress(
    commit: TaskCommit,
    plan: _WavePlan,
    next_index: int,
    committed_seq: int,
) -> None:
    """Emit a tournament-progress milestone when a wave crosses a cadence.

    Placed after the checkpoint commit, downstream of the caller's
    replay/supersession guard, so a redelivered match never re-announces
    progress. The final match is left to the finalizer's own "completed"
    event rather than reported twice.

    Reported per cadence boundary the wave *crossed*, not when the index
    happens to land on one. A wave advances the index by a variable stride,
    so an exact-multiple test silently skips boundaries it steps over -- it
    only ever worked because the stride and the cadence happened to line up.
    The message names the boundary rather than the index, so the feed reads
    as an even cadence whatever the stride.

    Args:
        commit: The leased task, its expected checkpoint seq, and db path.
        plan: The wave just judged and its position in the round.
        next_index: Round index the next task resumes at.
        committed_seq: Checkpoint sequence the wave's commit produced.
    """
    rounds = plan.rounds
    milestone = (next_index // RANKING_PROGRESS_EVERY) * RANKING_PROGRESS_EVERY
    crossed = plan.index // RANKING_PROGRESS_EVERY != (
        next_index // RANKING_PROGRESS_EVERY
    )
    if plan.wave and next_index < rounds and crossed:
        with store.transaction(commit.db_path) as conn:
            run = store.get_run(commit.task.run_id, conn=conn)
            if run is None or run.status not in _ACTIVE_RUN_STATUSES:
                return
            store.append_event(
                commit.task.run_id,
                "scientific_task",
                {
                    "task": "ranking",
                    "status": "running",
                    "checkpoint_seq": committed_seq,
                    "successor": None,
                    "message": f"Tournament match {milestone} of {rounds}",
                },
                conn=conn,
            )


async def _commit_ranking_match(
    commit: TaskCommit,
    state: dict[str, Any],
    plan: _WavePlan,
    result: _WaveResult,
) -> dict[str, Any]:
    """Checkpoint the wave's result, schedule its successor, and report.

    Args:
        commit: The leased task, its expected checkpoint seq, and db path.
        state: Workflow state carrying the wave's committed matchups.
        plan: The wave just judged and its position in the round.
        result: The tournament totals after folding the wave in.

    Returns:
        The task result: committed checkpoint, successor, and match tally.
    """
    next_index = result.next_index
    successor_type, successor_inputs = _ranking_match_successor(
        next_index,
        plan.rounds,
        result.total_calls,
        result.last_pair,
        result.model_usage,
    )
    committed_seq, successor_id = _save_state_and_enqueue_exact(
        commit,
        state,
        ExactSuccessor(
            task_type=successor_type,
            inputs=successor_inputs,
            idempotency_key=(
                f"ranking:match:{{checkpoint_seq}}:{next_index}"
                if successor_type == RANKING_MATCH_TASK
                else "ranking:finalize:{checkpoint_seq}"
            ),
        ),
    )
    await _emit_ranking_wave_progress(commit, plan, next_index, committed_seq)
    return {
        "checkpoint_seq": committed_seq,
        "successor_task_id": successor_id,
        "round_index": plan.index,
        "matches_committed": len(result.details),
    }


async def execute_ranking_match(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Judge and commit exactly one Elo matchup before scheduling another."""
    replay, state, current_seq = _restore_ranking_state(
        task, db_path, label="ranking match"
    )
    if replay is not None:
        return replay
    eligible = _ranking_eligible(state)
    index = int(task.inputs["round_index"])
    rounds = int(task.inputs["tournament_rounds"])
    plan = _prepare_ranking_wave(task, state, eligible, index, rounds)
    result = await _advance_ranking_wave(
        plan,
        state,
        eligible,
        _WaveResult(
            details=list(state.get("pending_ranking_matchups") or []),
            total_calls=int(task.inputs["total_llm_calls"]),
            next_index=index,
            last_pair=[],
            model_usage=dict(task.inputs.get("model_usage") or {}),
        ),
    )
    state["pending_ranking_matchups"] = result.details
    return await _commit_ranking_match(
        TaskCommit(task, current_seq, db_path), state, plan, result
    )


async def _commit_ranking_finalize(
    commit: TaskCommit,
    committed: dict[str, Any],
    update: dict[str, Any],
) -> dict[str, Any]:
    """Checkpoint the finalized tournament and report matches committed.

    The successor comes from the engine's route table for the same reason
    the fan-out aggregates' does (see ``_checkpoint_and_advance``): this is
    the only path production runs, so a literal here would survive a graph
    re-route that ``engine/tests/test_task_runtime.py`` reported as applied.
    """
    from co_scientist.task_runtime import next_task_type

    # ``co_scientist`` is unfollowed by the app's mypy, so this arrives as
    # ``Any``; restate the engine's declared type on the binding.
    successor: str | None = next_task_type("ranking", committed)
    if successor == "orchestrator" and _consume_outcome_refinement_gate(
        commit.task.run_id, committed, db_path=commit.db_path
    ):
        successor = None
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        commit, committed, successor
    )
    await _emit_node_completion(
        commit.task.run_id,
        NodeCompletion("ranking", successor, checkpoint_seq),
        committed,
        commit.db_path,
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "matches_committed": len(update.get("tournament_matchups", [])),
    }


def _consume_outcome_refinement_gate(
    run_id: str, state: dict[str, Any], *, db_path: str | None
) -> bool:
    """End the targeted child's ordinary gate cycle before pool evolution."""
    for hypothesis in state.get("hypotheses", []):
        provenance = hypothesis.enrichments.get("outcome_refinement")
        if not isinstance(provenance, dict):
            continue
        action_id = provenance.get("action_id")
        action = (
            store.get_outcome_refinement_action(
                run_id, str(action_id), db_path=db_path
            )
            if action_id
            else None
        )
        if (
            action is None
            or action.get("status") != "completed"
            or action.get("child_hypothesis_id") != hypothesis.id
            or provenance.get("outcome_id") != action.get("outcome_id")
            or provenance.get("parent_hypothesis_id")
            != action.get("hypothesis_id")
        ):
            continue
        hypothesis.enrichments.pop("outcome_refinement", None)
        return True
    return False


def _fold_ranking_telemetry(
    update: dict[str, Any], model_usage: dict[str, dict[str, Any]]
) -> None:
    """Fold the tournament's accumulated telemetry into its metrics delta.

    The per-match wave telemetry never reaches a checkpoint until here (see
    ``_WaveResult.model_usage``'s docstring): every intervening match commit
    uses ``_save_state_and_enqueue_exact``, which persists no metrics
    snapshot, so this is the sole point that folds it in.
    """
    from co_scientist.models import create_metrics_update, merge_metrics

    if not model_usage:
        return
    update["metrics"] = merge_metrics(
        update["metrics"], create_metrics_update(model_usage=model_usage)
    )


async def execute_ranking_finalize(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Finalize a sequential durable tournament and return to orchestration."""
    from co_scientist.agents.ranking.ranking import _finalize_ranking_result
    from co_scientist.task_runtime import apply_task_update

    replay, state, current_seq = _restore_ranking_state(
        task, db_path, label="ranking finalizer"
    )
    if replay is not None:
        return replay
    update = await _finalize_ranking_result(
        state,
        state["hypotheses"],
        list(state.get("pending_ranking_matchups") or []),
        int(task.inputs["tournament_rounds"]),
        int(task.inputs["total_llm_calls"]),
    )
    _fold_ranking_telemetry(update, dict(task.inputs.get("model_usage") or {}))
    committed = apply_task_update(state, update)
    committed.pop("pending_ranking_matchups", None)
    return await _commit_ranking_finalize(
        TaskCommit(task, current_seq, db_path), committed, update
    )
