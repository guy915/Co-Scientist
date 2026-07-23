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
from app.report_render import make_emitter
from app.store import ScientificTask


def _ranking_eligible(state: dict[str, Any]) -> list[Any]:
    """Return hypotheses eligible for a tournament under engine policy.

    Ideas the pre-ranking evidence gate quarantined (``evidence_blocked``) are
    excluded alongside deep-verification-undermined and review-rejected ideas,
    so an unsupported or contradicted claim never influences the decisive Elo
    tournament even though the report gate would later drop it. The predicate
    lives on ``Hypothesis.is_rankable`` so the durable path and the engine
    scheduler's coverage accounting stay in sync (a mismatch loops the
    orchestrator on ranking).
    """
    return [
        hypothesis
        for hypothesis in state["hypotheses"]
        if hypothesis.is_rankable()
    ]


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
    if len(eligible) < 2:
        return None
    rounds, *_ = await _prepare_ranking_round(state, eligible)
    state["pending_ranking_matchups"] = []
    committed_seq, successor_id = _save_state_and_enqueue_exact(
        TaskCommit(task, checkpoint_seq, db_path),
        state,
        ExactSuccessor(
            task_type=RANKING_MATCH_TASK,
            inputs={
                "round_index": 0,
                "tournament_rounds": rounds,
                "total_llm_calls": 0,
                "previous_pair": [],
            },
            idempotency_key="ranking:match:{checkpoint_seq}:0",
        ),
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
    from co_scientist.checkpoint import restore_workflow_state

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
) -> tuple[str, dict[str, Any]]:
    """Return the next ranking task type and its scheduling inputs."""
    if next_index < rounds:
        return RANKING_MATCH_TASK, {
            "round_index": next_index,
            "tournament_rounds": rounds,
            "total_llm_calls": total_calls,
            "previous_pair": last_pair,
        }
    return RANKING_FINALIZE_TASK, {
        "tournament_rounds": rounds,
        "total_llm_calls": total_calls,
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
        emit = make_emitter(commit.task.run_id, db_path=commit.db_path)
        await emit(
            "scientific_task",
            {
                "task": "ranking",
                "status": "running",
                "checkpoint_seq": committed_seq,
                "successor": None,
                "message": f"Tournament match {milestone} of {rounds}",
            },
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
        next_index, plan.rounds, result.total_calls, result.last_pair
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
        ),
    )
    state["pending_ranking_matchups"] = result.details
    return await _commit_ranking_match(
        TaskCommit(task, current_seq, db_path), state, plan, result
    )


async def _commit_ranking_finalize(
    task: ScientificTask,
    committed: dict[str, Any],
    update: dict[str, Any],
    current_seq: int,
    db_path: str | None,
) -> dict[str, Any]:
    """Checkpoint the finalized tournament and report matches committed."""
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        task,
        committed,
        "orchestrator",
        expected_checkpoint_seq=current_seq,
        db_path=db_path,
    )
    await _emit_node_completion(
        task.run_id,
        NodeCompletion("ranking", "orchestrator", checkpoint_seq),
        committed,
        db_path,
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "matches_committed": len(update.get("tournament_matchups", [])),
    }


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
    committed = apply_task_update(state, update)
    committed.pop("pending_ranking_matchups", None)
    return await _commit_ranking_finalize(
        task, committed, update, current_seq, db_path
    )
