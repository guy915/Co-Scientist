"""Durable tournament execution: sequential ranking-match waves.

Schedules the ranking chain from a committed checkpoint, judges bounded
waves of Elo matchups (one durable task per wave), and finalizes the
tournament back into orchestration. Split from ``app.engine_tasks``,
which re-exports these names for compatibility.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.engine_tasks_support import (
    RANKING_FINALIZE_TASK,
    RANKING_MATCH_TASK,
    RANKING_PROGRESS_EVERY,
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
        task,
        state,
        RANKING_MATCH_TASK,
        {
            "round_index": 0,
            "tournament_rounds": rounds,
            "total_llm_calls": 0,
            "previous_pair": [],
        },
        idempotency_key="ranking:match:{checkpoint_seq}:0",
        expected_checkpoint_seq=checkpoint_seq,
        db_path=db_path,
    )
    return {
        "checkpoint_seq": committed_seq,
        "successor_task_id": successor_id,
        "tournament_rounds": rounds,
        "node": "ranking",
    }


# How many matchups one durable task judges concurrently. Bounded so a wave
# still commits a checkpoint often enough to be a useful resume point, and so
# the pool's Elo ratings re-adapt between waves rather than drifting across a
# whole round judged from one stale snapshot.
RANKING_WAVE_SIZE = 5


def _ranking_wave(
    candidates: list[Any],
    previous_pair: frozenset[str],
    index: int,
    rounds: int,
) -> list[Any]:
    """Return the distinct matchups this task should judge concurrently.

    Skips the pair the previous wave ended on (the existing rematch guard) and
    never repeats a pair inside one wave, since every pairing in a wave is
    drawn from the same Elo snapshot and would otherwise be judged twice.
    Never runs past the round budget.
    """
    remaining = max(0, rounds - index)
    wave: list[Any] = []
    seen: set[frozenset[str]] = {previous_pair} if previous_pair else set()
    for pair in candidates:
        if len(wave) >= min(RANKING_WAVE_SIZE, remaining):
            break
        key = frozenset({pair[0].id, pair[1].id})
        if key in seen:
            continue
        seen.add(key)
        wave.append(pair)
    if not wave and candidates and remaining:
        # Every candidate was a repeat; judging the best one again still makes
        # progress and matches the previous one-per-task fallback.
        wave.append(candidates[0])
    return wave


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


def _prepare_ranking_wave(
    task: ScientificTask,
    state: dict[str, Any],
    eligible: list[Any],
    index: int,
    rounds: int,
) -> list[Any]:
    """Build this task's wave of distinct matchups to judge concurrently.

    Enough pairings are drawn to fill a wave, plus one for the rematch guard
    to skip. The streaming path asks for three because it then picks exactly
    one; the durable path inherited that number when it started judging
    waves, which silently capped every wave at three no matter how many
    rounds remained. A short wave is not lost work, it is another sequential
    durable task: the ultra run spent about two hours across 178 of them.

    A matchup is three debate turns of real model work (~45s), so
    one-per-task ran a 128-match round at a concurrency of one -- about 94
    minutes of wall clock for ~20 minutes of work. Judging a wave instead
    draws every pairing in it from the same Elo snapshot, which is the cost
    of the parallelism: adaptation happens at wave boundaries rather than
    after every single match.
    """
    from co_scientist.agents.ranking.ranking import _build_tournament_pairings

    candidates = _build_tournament_pairings(
        eligible,
        min(RANKING_WAVE_SIZE + 1, rounds),
        state["research_goal"],
        int(state.get("current_iteration", 0)) * 10_000 + index,
    )
    previous_pair = frozenset(
        str(item) for item in task.inputs["previous_pair"]
    )
    return _ranking_wave(candidates, previous_pair, index, rounds)


async def _judge_one_matchup(
    pair: tuple[Any, Any],
    offset: int,
    index: int,
    state: dict[str, Any],
    context: tuple[Any, Any, Any, Any, Any],
    debate_turns: int,
) -> tuple[str, dict[str, Any]]:
    """Judge one matchup of a wave against the wave's shared context."""
    from co_scientist.agents.ranking.ranking import judge_matchup

    guidance, registry, meta_review, setup, focus = context
    judgement: tuple[str, dict[str, Any]] = await judge_matchup(
        pair[0],
        pair[1],
        state["research_goal"],
        state["model_name"],
        guidance,
        run_id=state.get("run_id"),
        matchup_index=index + offset,
        tool_registry=registry,
        meta_review=meta_review,
        run_setup_guidance=setup,
        run_focus_guidance=focus,
        debate_turns=debate_turns,
    )
    return judgement


async def _judge_wave_matchups(
    wave: list[Any],
    state: dict[str, Any],
    eligible: list[Any],
    index: int,
) -> tuple[list[tuple[str, dict[str, Any]]], list[int]]:
    """Judge one wave of matchups concurrently against a shared Elo snapshot.

    The engine's ranking semaphore bounds the real fan-out; gather only
    offers it more than one call to bound.
    """
    from co_scientist.agents.ranking.ranking import (
        _gather_tournament_context,
        _matchup_debate_turns,
        _median_elo,
    )

    context = _gather_tournament_context(state)
    median = _median_elo(eligible)
    depths = [_matchup_debate_turns(pair[0], pair[1], median) for pair in wave]
    judged = await asyncio.gather(
        *(
            _judge_one_matchup(
                pair, offset, index, state, context, depths[offset]
            )
            for offset, pair in enumerate(wave)
        )
    )
    return list(judged), depths


def _apply_wave_elo(
    wave: list[Any],
    judged: list[tuple[str, dict[str, Any]]],
    depths: list[int],
    state: dict[str, Any],
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Apply a judged wave's Elo updates in wave order.

    Elo is applied in wave order so the committed result is independent of
    the order the concurrent judgements happened to return in.
    """
    from co_scientist.agents.ranking.ranking import (
        _apply_matchup_elo,
        _build_matchup_detail,
    )
    from co_scientist.constants import ELO_K_FACTOR

    k_factor = int(state.get("elo_k_factor") or ELO_K_FACTOR)
    details: list[dict[str, Any]] = []
    total_calls = 0
    last_pair: list[str] = []
    for offset, (pair, (winner, response)) in enumerate(
        zip(wave, judged, strict=True)
    ):
        hypothesis_a, hypothesis_b = pair
        outcome = _apply_matchup_elo(
            hypothesis_a, hypothesis_b, winner, k_factor=k_factor
        )
        details.append(
            _build_matchup_detail(
                hypothesis_a, hypothesis_b, winner, response, outcome
            )
        )
        total_calls += depths[offset]
        last_pair = [hypothesis_a.id, hypothesis_b.id]
    return details, total_calls, last_pair


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
    task: ScientificTask,
    wave: list[Any],
    index: int,
    next_index: int,
    rounds: int,
    committed_seq: int,
    db_path: str | None,
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
    """
    milestone = (next_index // RANKING_PROGRESS_EVERY) * RANKING_PROGRESS_EVERY
    crossed = index // RANKING_PROGRESS_EVERY != (
        next_index // RANKING_PROGRESS_EVERY
    )
    if wave and next_index < rounds and crossed:
        emit = make_emitter(task.run_id, db_path=db_path)
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


async def _advance_ranking_wave(
    wave: list[Any],
    state: dict[str, Any],
    eligible: list[Any],
    index: int,
    rounds: int,
    details: list[dict[str, Any]],
    total_calls: int,
) -> tuple[list[dict[str, Any]], int, int, list[str]]:
    """Judge a wave (if any) and fold its results into the running totals."""
    if not wave:
        return details, total_calls, rounds, []
    judged, depths = await _judge_wave_matchups(wave, state, eligible, index)
    new_details, calls_delta, last_pair = _apply_wave_elo(
        wave, judged, depths, state
    )
    return (
        details + new_details,
        total_calls + calls_delta,
        index + len(wave),
        last_pair,
    )


async def _commit_ranking_match(
    task: ScientificTask,
    state: dict[str, Any],
    wave: list[Any],
    index: int,
    next_index: int,
    rounds: int,
    total_calls: int,
    last_pair: list[str],
    details: list[dict[str, Any]],
    current_seq: int,
    db_path: str | None,
) -> dict[str, Any]:
    """Checkpoint the wave's result, schedule its successor, and report."""
    successor_type, successor_inputs = _ranking_match_successor(
        next_index, rounds, total_calls, last_pair
    )
    committed_seq, successor_id = _save_state_and_enqueue_exact(
        task,
        state,
        successor_type,
        successor_inputs,
        idempotency_key=(
            f"ranking:match:{{checkpoint_seq}}:{next_index}"
            if successor_type == RANKING_MATCH_TASK
            else "ranking:finalize:{checkpoint_seq}"
        ),
        expected_checkpoint_seq=current_seq,
        db_path=db_path,
    )
    await _emit_ranking_wave_progress(
        task, wave, index, next_index, rounds, committed_seq, db_path
    )
    return {
        "checkpoint_seq": committed_seq,
        "successor_task_id": successor_id,
        "round_index": index,
        "matches_committed": len(details),
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
    wave = _prepare_ranking_wave(task, state, eligible, index, rounds)
    details, total_calls, next_index, last_pair = await _advance_ranking_wave(
        wave,
        state,
        eligible,
        index,
        rounds,
        list(state.get("pending_ranking_matchups") or []),
        int(task.inputs["total_llm_calls"]),
    )
    state["pending_ranking_matchups"] = details
    return await _commit_ranking_match(
        task,
        state,
        wave,
        index,
        next_index,
        rounds,
        total_calls,
        last_pair,
        details,
        current_seq,
        db_path,
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
        "ranking",
        "orchestrator",
        committed,
        checkpoint_seq,
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
