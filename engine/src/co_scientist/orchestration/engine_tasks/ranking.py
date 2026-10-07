from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from co_scientist.core.constants import RANKING_WAVE_SIZE as RANKING_WAVE_SIZE
from co_scientist.core.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.orchestration.engine_tasks.support import (
    RANKING_FINALIZE_TASK,
    RANKING_MATCH_TASK,
    RANKING_PROGRESS_EVERY,
    ExactSuccessor,
    NodeCompletion,
    TaskCommit,
    _emit_node_completion,
    _save_state_and_enqueue,
    _save_state_and_enqueue_exact,
    leased_state,
    merge_usage_snapshots,
)
from co_scientist.orchestration.repository import events, runs
from co_scientist.orchestration.repository.runs_views import _ACTIVE_RUN_STATUSES
from co_scientist.platform import db
from co_scientist.platform.db.models import ScientificTask
from co_scientist.platform.llm import scoped_telemetry
from co_scientist.science.ranking import RankingJudgement, RankingJudgingContext

if TYPE_CHECKING:
    from co_scientist.domains.research_state.state import WorkflowState

logger = logging.getLogger(__name__)

# The engine owns wave width and judge semaphore size; mismatches silently
# serialize work.


def _wave_size() -> int:
    """The engine owns both wave width and judge semaphore size so
    throttling cannot silently serialize an oversized wave.
    """
    from co_scientist.science.ranking.ranking_debate import (
        effective_ranking_wave_size,
    )

    return int(effective_ranking_wave_size())


@dataclass(frozen=True)
class _WavePlan:
    wave: list[Any]
    index: int
    rounds: int


@dataclass(frozen=True)
class _WaveResult:
    details: list[dict[str, Any]]
    total_calls: int
    next_index: int
    last_pair: list[str]
    model_usage: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class _JudgedWave:
    pairs: list[Any]
    judgements: list[RankingJudgement]


@dataclass(frozen=True)
class _WaveJudgeContext:
    context: RankingJudgingContext
    index: int


def _judged_pairs(state: dict[str, Any]) -> set[frozenset[str]]:
    """Committed matchup history survives resume; retaining only the last
    pair would re-offer earlier comparisons.
    """
    judged: set[frozenset[str]] = set()
    for detail in state.get("pending_ranking_matchups") or []:
        a_id = detail.get("hypothesis_a_id")
        b_id = detail.get("hypothesis_b_id")
        if a_id and b_id:
            judged.add(frozenset({str(a_id), str(b_id)}))
    return judged


def _ranking_wave(
    candidates: list[Any],
    previous_pair: frozenset[str],
    index: int,
    rounds: int,
    wave_size: int,
) -> list[Any]:
    """Repeated pairs inflate Elo without testing new opponents; exhaustion
    ends the tournament instead of rejudging a fallback pair.
    """
    remaining = max(0, rounds - index)
    wave: list[Any] = []
    seen: set[frozenset[str]] = {previous_pair} if previous_pair else set()
    for pair in candidates:
        if len(wave) >= min(wave_size, remaining):
            break
        key = frozenset({pair[0].id, pair[1].id})
        if key in seen:
            continue
        seen.add(key)
        wave.append(pair)
    return wave


def _prepare_ranking_wave(
    task: ScientificTask,
    state: dict[str, Any],
    eligible: list[Any],
    index: int,
    rounds: int,
) -> _WavePlan:
    """Concurrent matches share one Elo snapshot; rating adaptation
    deliberately occurs at wave boundaries.
    """
    from co_scientist.science.ranking import build_tournament_pairings

    wave_size = _wave_size()
    candidates = build_tournament_pairings(
        eligible,
        min(wave_size + 1, rounds),
        state["research_goal"],
        int(state.get("current_iteration", 0)) * 10_000 + index,
        judged=_judged_pairs(state),
    )
    previous_pair = frozenset(str(item) for item in task.inputs["previous_pair"])
    return _WavePlan(
        wave=_ranking_wave(candidates, previous_pair, index, rounds, wave_size),
        index=index,
        rounds=rounds,
    )


async def _judge_one_matchup(
    pair: tuple[Any, Any],
    offset: int,
    judge_context: _WaveJudgeContext,
) -> RankingJudgement:
    from co_scientist.science.ranking import judge_ranking_matchup

    result: RankingJudgement = await judge_ranking_matchup(
        pair, judge_context.context, judge_context.index + offset
    )
    return result


def _surviving_judgements(
    wave: list[Any],
    judged: list[Any],
) -> _JudgedWave:
    """Ordinary judge failures isolate one matchup; rate-limit parking and
    exhausted budgets remain task control flow, never missing verdicts.
    """
    for result in judged:
        if isinstance(result, TASK_CONTROL_FLOW_ERRORS):
            raise result
    pairs: list[Any] = []
    judgements: list[RankingJudgement] = []
    for offset, result in enumerate(judged):
        if isinstance(result, BaseException):
            logger.warning(
                "Ranking matchup %s failed and was dropped from its wave: %s",
                offset,
                result,
            )
            continue
        pairs.append(wave[offset])
        judgements.append(result)
    return _JudgedWave(pairs, judgements)


async def _judge_wave_matchups(
    plan: _WavePlan,
    state: dict[str, Any],
    eligible: list[Any],
) -> _JudgedWave:
    from co_scientist.science.ranking import (
        prepare_ranking_judging_context,
        prepare_ranking_prompt_context,
    )

    # Durable judging deliberately omits preferences and shares one checkpointed
    # guidance/median snapshot across the wave.
    prompt = prepare_ranking_prompt_context(cast("WorkflowState", state))
    context = prepare_ranking_judging_context(prompt, eligible)
    judge_context = _WaveJudgeContext(context, plan.index)
    judged = await asyncio.gather(
        *(_judge_one_matchup(pair, offset, judge_context) for offset, pair in enumerate(plan.wave)),
        return_exceptions=True,
    )
    return _surviving_judgements(plan.wave, list(judged))


def _apply_wave_elo(
    wave: list[Any],
    judged: list[RankingJudgement],
    state: dict[str, Any],
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Apply verdicts in wave order so shared hypotheses start each rating
    update where their previous matchup left them.
    """
    from co_scientist.core.constants import ELO_K_FACTOR
    from co_scientist.science.ranking import apply_ranking_matchup

    k_factor = int(state.get("elo_k_factor") or ELO_K_FACTOR)
    iteration = int(state.get("current_iteration", 0))
    details: list[dict[str, Any]] = []
    total_calls = 0
    last_pair: list[str] = []
    for pair, judgement in zip(wave, judged, strict=True):
        result = apply_ranking_matchup(
            pair, judgement, k_factor=k_factor, current_iteration=iteration
        )
        details.append(result.detail)
        total_calls += result.llm_calls
        last_pair = [pair[0].id, pair[1].id]
    return details, total_calls, last_pair


async def _advance_ranking_wave(
    plan: _WavePlan,
    state: dict[str, Any],
    eligible: list[Any],
    carried: _WaveResult,
) -> _WaveResult:
    if not plan.wave:
        return _WaveResult(
            carried.details,
            carried.total_calls,
            plan.rounds,
            [],
            carried.model_usage,
        )
    with scoped_telemetry("ranking") as telemetry:
        survived = await _judge_wave_matchups(plan, state, eligible)
    new_details, calls_delta, last_pair = _apply_wave_elo(
        survived.pairs, survived.judgements, state
    )
    # Failed matchups spend their budget slot; rewinding would re-offer the same
    # pair indefinitely.
    return _WaveResult(
        details=carried.details + new_details,
        total_calls=carried.total_calls + calls_delta,
        next_index=plan.index + len(plan.wave),
        last_pair=last_pair,
        model_usage=merge_usage_snapshots([carried.model_usage, telemetry.snapshot()]),
    )


def _ranking_eligible(state: dict[str, Any]) -> list[Any]:
    """Engine admission and peer-review predicates stay authoritative,
    including newcomers admitted before a retried ranking task.
    """
    from co_scientist.domains.research_state.models import has_peer_review

    return [
        hypothesis
        for hypothesis in state["hypotheses"]
        if hypothesis.is_rankable() and has_peer_review(hypothesis)
    ]


def _ranking_chain_skipped(state: dict[str, Any], eligible: list[Any]) -> bool:
    from co_scientist.science.scheduling.tournament import remaining_ranking_rounds

    if len(eligible) < 2:
        return True
    rounds_left = remaining_ranking_rounds(cast("WorkflowState", state), state["hypotheses"])
    # An empty tournament resets pending matches; skip exhausted whole-run
    # budgets to retain already judged history.
    return rounds_left < 1


def _enqueue_first_ranking_match(
    task: ScientificTask,
    state: dict[str, Any],
    checkpoint_seq: int,
    rounds: int,
    db_path: str | None,
) -> tuple[int, str]:
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
    from co_scientist.science.ranking import prepare_ranking_round

    eligible = _ranking_eligible(state)
    if _ranking_chain_skipped(state, eligible):
        return None
    rounds, *_ = await prepare_ranking_round(cast("WorkflowState", state), eligible)
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


def _ranking_match_successor(
    next_index: int,
    rounds: int,
    total_calls: int,
    last_pair: list[str],
    model_usage: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
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
    """Emit only after commit and replay guards; cadence crossings, not
    exact multiples, cover variable wave strides.
    """
    rounds = plan.rounds
    milestone = (next_index // RANKING_PROGRESS_EVERY) * RANKING_PROGRESS_EVERY
    crossed = plan.index // RANKING_PROGRESS_EVERY != (next_index // RANKING_PROGRESS_EVERY)
    if plan.wave and next_index < rounds and crossed:
        with db.transaction(commit.db_path) as conn:
            run = runs.get_run(commit.task.run_id, conn=conn)
            if run is None or run.status not in _ACTIVE_RUN_STATUSES:
                return
            events.append_event(
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
    replay, state, current_seq = leased_state(task, db_path, label="ranking match")
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
    return await _commit_ranking_match(TaskCommit(task, current_seq, db_path), state, plan, result)


async def _commit_ranking_finalize(
    commit: TaskCommit,
    committed: dict[str, Any],
    update: dict[str, Any],
) -> dict[str, Any]:
    """Finalized successors come from the engine route table, avoiding a
    durable path that ignores routing changes.
    """
    from co_scientist.orchestration.task_runtime import next_task_type

    successor = next_task_type("ranking", cast("WorkflowState", committed))
    checkpoint_seq, successor_id = _save_state_and_enqueue(commit, committed, successor)
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


def _fold_ranking_telemetry(update: dict[str, Any], model_usage: dict[str, dict[str, Any]]) -> None:
    """Wave telemetry accumulates across match checkpoints and folds into
    scientific metrics once at tournament finalization.
    """
    from co_scientist.domains.research_state.models import create_metrics_update, merge_metrics

    if not model_usage:
        return
    update["metrics"] = merge_metrics(
        update["metrics"], create_metrics_update(model_usage=model_usage)
    )


async def execute_ranking_finalize(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    from co_scientist.orchestration.task_runtime import apply_task_update
    from co_scientist.science.ranking import finalize_ranking

    replay, state, current_seq = leased_state(task, db_path, label="ranking finalizer")
    if replay is not None:
        return replay
    update = await finalize_ranking(
        cast("WorkflowState", state),
        state["hypotheses"],
        list(state.get("pending_ranking_matchups") or []),
        int(task.inputs["tournament_rounds"]),
        int(task.inputs["total_llm_calls"]),
    )
    _fold_ranking_telemetry(update, dict(task.inputs.get("model_usage") or {}))
    committed = cast("dict[str, Any]", apply_task_update(cast("WorkflowState", state), update))
    committed.pop("pending_ranking_matchups", None)
    return await _commit_ranking_finalize(TaskCommit(task, current_seq, db_path), committed, update)


__all__ = ["RANKING_WAVE_SIZE"]
