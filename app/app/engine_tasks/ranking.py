"""Durable tournament execution: sequential ranking-match waves."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from co_scientist.agents.ranking import RankingJudgement, RankingJudgingContext
from co_scientist.constants import RANKING_WAVE_SIZE as RANKING_WAVE_SIZE
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.llm import scoped_telemetry

import app.store as store
from app.engine_tasks.support import (
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
from app.store import ScientificTask
from app.store.runs_views import _ACTIVE_RUN_STATUSES

logger = logging.getLogger(__name__)

# Re-exported so ``app.engine_tasks.RANKING_WAVE_SIZE`` keeps resolving. The
# engine owns the number: it also sizes the judge semaphore, and the two
# must agree or the wave serializes inside the task.


def _wave_size() -> int:
    """Return the width the next wave should use.

    Read from the engine rather than declared here so the wave and the
    judge semaphore that bounds it cannot drift apart. A semaphore narrower
    than the wave silently serializes it into batches, which looks like a
    wide wave that is inexplicably slow; the engine owns both numbers and
    steps them down together when the provider throttles.
    """
    from co_scientist.agents.ranking.ranking_debate import (
        effective_ranking_wave_size,
    )

    return int(effective_ranking_wave_size())


@dataclass(frozen=True)
class _WavePlan:
    """The matchups one ranking task judges and where they sit in a round.

    Attributes:
        wave: Distinct matchups this task judges concurrently.
        index: Round index the wave starts at.
        rounds: Total matchups budgeted for the tournament.
    """

    wave: list[Any]
    index: int
    rounds: int


@dataclass(frozen=True)
class _WaveResult:
    """What judging one wave contributed to the running tournament totals.

    Attributes:
        details: Every matchup detail committed so far this task.
        total_calls: Cumulative LLM calls the tournament has spent.
        next_index: Round index the next task resumes at.
        last_pair: Hypothesis ids of the wave's final matchup (rematch guard).
        model_usage: Per-(phase, model) telemetry folded from every wave
            judged so far this tournament (finding L3's cost-accounting
            counterpart), carried through the sequential match chain since
            only the finalize task's checkpoint commits it (see
            ``_commit_ranking_match`` in ``app.engine_tasks.ranking``).
    """

    details: list[dict[str, Any]]
    total_calls: int
    next_index: int
    last_pair: list[str]
    model_usage: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class _JudgedWave:
    """Surviving verdicts in wave order, carrying budgeted debate depths."""

    pairs: list[Any]
    judgements: list[RankingJudgement]


@dataclass(frozen=True)
class _WaveJudgeContext:
    """One shared scientific context and a wave's matchup numbering base."""

    context: RankingJudgingContext
    index: int


def _judged_pairs(state: dict[str, Any]) -> set[frozenset[str]]:
    """Every matchup this tournament has already judged.

    Read from the committed ``pending_ranking_matchups`` rather than carried
    in task inputs, so it survives a resume and needs no schema change: the
    details are the durable record of what was judged. A wave that only knew
    the previous pair would re-offer everything before it.
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
    """Return the distinct matchups this task should judge concurrently.

    Skips the pair the previous wave ended on (the existing rematch guard) and
    never repeats a pair inside one wave, since every pairing in a wave is
    drawn from the same Elo snapshot and would otherwise be judged twice.
    Never runs past the round budget.

    Returns empty when the tournament has no comparison left to make, which
    ends it. This used to fall back to judging ``candidates[0]`` again on the
    grounds that a repeat still made progress. It does not: re-judging one
    pair moves the winner's rating without testing it against anything new.
    A pool with two rankable ideas has exactly one comparison, and every
    production run spent its whole tournament replaying it -- six matches,
    one pair, the winner reported at 1259 as though it had beaten six
    opponents.
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
    """Build this task's wave of distinct matchups to judge concurrently.

    Enough pairings are drawn to fill a wave, plus one for the rematch guard
    to skip. A short wave is not lost work, it is another sequential durable
    task: the ultra run spent about two hours across 178 of them.

    A matchup is a multi-turn scientific debate of real model work (up to
    ten judged turns, settled early on consensus), so
    one-per-task ran a 128-match round at a concurrency of one -- about 94
    minutes of wall clock for ~20 minutes of work. Judging a wave instead
    draws every pairing in it from the same Elo snapshot, which is the cost
    of the parallelism: adaptation happens at wave boundaries rather than
    after every single match. At the current width a standard tier's
    12-match pass is one wave and an ultra tier's 32 is three, so the
    snapshot a matchup is judged against is at most one pass stale.

    Args:
        task: The leased ranking-match task.
        state: Restored workflow state for this tournament.
        eligible: Hypotheses eligible for a matchup.
        index: Round index this wave starts at.
        rounds: Total matchups budgeted for the tournament.

    Returns:
        The wave to judge, with the round position it occupies.
    """
    from co_scientist.agents.ranking import build_tournament_pairings

    wave_size = _wave_size()
    candidates = build_tournament_pairings(
        eligible,
        min(wave_size + 1, rounds),
        state["research_goal"],
        int(state.get("current_iteration", 0)) * 10_000 + index,
        judged=_judged_pairs(state),
    )
    previous_pair = frozenset(
        str(item) for item in task.inputs["previous_pair"]
    )
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
    """Judge one pair against the shared wave snapshot."""
    from co_scientist.agents.ranking import judge_ranking_matchup

    result: RankingJudgement = await judge_ranking_matchup(
        pair, judge_context.context, judge_context.index + offset
    )
    return result


def _surviving_judgements(
    wave: list[Any],
    judged: list[Any],
) -> _JudgedWave:
    """Drop the matchups whose judge raised, keeping their siblings.

    A judge failure is per-matchup -- a throttled call, a malformed verdict
    after every retry -- and the wave's other comparisons are finished and
    paid for. Letting one exception out of the gather cancelled them all,
    failed the wave task, and spent one of its three attempts re-judging
    work that had already succeeded.

    Neither control-flow error is per-matchup, and neither costs an
    attempt, so both leave through the gather rather than being dropped
    with the ordinary failures: a park returns the row to ``queued`` with
    its attempt *undone*, and a spent call budget ends the run. Dropping
    them re-runs the rest of the wave against a cap that has not reset --
    the same trade the mature reviews lost eleven items to in run
    bc77950f.

    Raises:
        LLMRateLimitParkError: A platform cap the worker must park on.
        LLMCallBudgetExceededError: The run's spend ceiling is exhausted.
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
    """Judge one wave of matchups concurrently against a shared Elo snapshot.

    The engine's ranking semaphore bounds the real fan-out; gather only
    offers it more than one call to bound. Per-matchup failures are
    isolated (see ``_surviving_judgements``) rather than raised, so the
    return is the *surviving* subset, not the whole wave.

    Args:
        plan: The wave to judge and its position in the round.
        state: Restored workflow state for this tournament.
        eligible: Hypotheses eligible for a matchup (the Elo snapshot).

    Returns:
        The matchups that produced a verdict, with their judgements and
        debate depths, in wave order.
    """
    from co_scientist.agents.ranking import (
        prepare_ranking_judging_context,
        prepare_ranking_prompt_context,
    )

    # Durable judging intentionally omits preferences and snapshots the
    # guidance and O(pool size) median once for the entire checkpointed wave.
    prompt = prepare_ranking_prompt_context(state)
    context = prepare_ranking_judging_context(prompt, eligible)
    judge_context = _WaveJudgeContext(context, plan.index)
    judged = await asyncio.gather(
        *(
            _judge_one_matchup(pair, offset, judge_context)
            for offset, pair in enumerate(plan.wave)
        ),
        return_exceptions=True,
    )
    return _surviving_judgements(plan.wave, list(judged))


def _apply_wave_elo(
    wave: list[Any],
    judged: list[RankingJudgement],
    state: dict[str, Any],
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Apply verdicts in wave order, charging actual debate calls.

    Judging may finish in any order, but a shared hypothesis must start
    each Elo commit at the rating its previous matchup left it at.
    """
    from co_scientist.agents.ranking import apply_ranking_matchup
    from co_scientist.constants import ELO_K_FACTOR

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
    """Judge a wave (if any) and fold its results into the running totals.

    Args:
        plan: The wave to judge and its position in the round.
        state: Restored workflow state for this tournament.
        eligible: Hypotheses eligible for a matchup (the Elo snapshot).
        carried: Details and LLM calls the tournament already accumulated.

    Returns:
        The updated running totals; an empty wave jumps to the round end.
    """
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
    # The round index advances by the whole wave, not by what survived: a
    # dropped matchup consumed its slot in the budget, and rewinding the
    # index would re-offer the same pairing to the next task forever.
    return _WaveResult(
        details=carried.details + new_details,
        total_calls=carried.total_calls + calls_delta,
        next_index=plan.index + len(plan.wave),
        last_pair=last_pair,
        model_usage=merge_usage_snapshots(
            [carried.model_usage, telemetry.snapshot()]
        ),
    )


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
    from co_scientist.agents.ranking import remaining_ranking_rounds

    if len(eligible) < 2:
        return True
    # The app's mypy config skips following ``co_scientist`` imports, so the
    # engine's declared ``-> int`` arrives here as ``Any``. Restate it on the
    # binding rather than returning an unchecked comparison.
    rounds_left: int = remaining_ranking_rounds(state, state["hypotheses"])
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
    from co_scientist.agents.ranking import prepare_ranking_round

    eligible = _ranking_eligible(state)
    if _ranking_chain_skipped(state, eligible):
        return None
    rounds, *_ = await prepare_ranking_round(state, eligible)
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
    replay, state, current_seq = leased_state(
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
    from co_scientist.agents.ranking import finalize_ranking
    from co_scientist.task_runtime import apply_task_update

    replay, state, current_seq = leased_state(
        task, db_path, label="ranking finalizer"
    )
    if replay is not None:
        return replay
    update = await finalize_ranking(
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


__all__ = ["RANKING_WAVE_SIZE"]
