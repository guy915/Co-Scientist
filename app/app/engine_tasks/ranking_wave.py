"""Wave building and judging for the durable ranking tournament.

One durable ranking task judges a bounded *wave* of Elo matchups: this
module owns the value objects describing a wave, the pairing selection, the
concurrent judging, and the Elo application that folds a judged wave back
into the running totals. Split from ``app.engine_tasks.ranking``, which
re-exports the names callers use so its namespace keeps resolving.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

# Re-exported so ``app.engine_tasks.RANKING_WAVE_SIZE`` keeps resolving. The
# engine owns the number: it also sizes the judge semaphore, and the two
# must agree or the wave serializes inside the task.
from co_scientist.constants import (
    RANKING_WAVE_SIZE as RANKING_WAVE_SIZE,
)
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.llm import scoped_telemetry

from app.engine_tasks.telemetry import merge_usage_snapshots
from app.store import ScientificTask

logger = logging.getLogger(__name__)


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
    """The subset of a wave that produced a verdict, in wave order.

    Attributes:
        pairs: Matchups whose judge returned; never the ones that raised.
        judgements: Each surviving matchup's (winner, response) verdict.
        depths: Each surviving matchup's budgeted debate depth.
    """

    pairs: list[Any]
    judgements: list[tuple[str, dict[str, Any]]]
    depths: list[int]


@dataclass(frozen=True)
class _WaveJudgeContext:
    """Per-wave context shared by every matchup a wave judges.

    Attributes:
        state: Restored workflow state the wave is judged against.
        context: The engine's gathered tournament context tuple.
        index: Round index the wave starts at (matchup numbering base).
    """

    state: dict[str, Any]
    context: tuple[Any, Any, Any, Any, Any]
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
    from co_scientist.agents.ranking.ranking import _build_tournament_pairings

    wave_size = _wave_size()
    candidates = _build_tournament_pairings(
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
    debate_turns: int,
) -> tuple[str, dict[str, Any]]:
    """Judge one matchup of a wave against the wave's shared context.

    Args:
        pair: The two hypotheses to judge.
        offset: Position of this matchup inside its wave.
        judge_context: State, tournament context, and the wave's base index.
        debate_turns: Debate depth this matchup was assigned.

    Returns:
        The judged winner and its raw debate response.
    """
    from co_scientist.agents.ranking.ranking import (
        _DebateContext,
        judge_matchup,
    )

    state = judge_context.state
    guidance, registry, meta_review, setup, focus = judge_context.context
    debate_ctx = _DebateContext(
        pair[0],
        pair[1],
        state["research_goal"],
        state["model_name"],
        supervisor_guidance=guidance,
        meta_review=meta_review,
        tool_registry=registry,
        run_setup_guidance=setup,
        run_focus_guidance=focus,
        run_id=state.get("run_id"),
        matchup_index=judge_context.index + offset,
        # The scientist's evaluation criteria govern the judge's verdict
        # (finding A2); read here because the durable wave path, not the
        # engine node, is where this run's judging happens.
        criteria=state.get("criteria"),
    )
    judgement: tuple[str, dict[str, Any]] = await judge_matchup(
        debate_ctx, debate_turns=debate_turns
    )
    return judgement


def _surviving_judgements(
    wave: list[Any],
    judged: list[Any],
    depths: list[int],
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
    judgements: list[tuple[str, dict[str, Any]]] = []
    kept_depths: list[int] = []
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
        kept_depths.append(depths[offset])
    return _JudgedWave(pairs, judgements, kept_depths)


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
    from co_scientist.agents.ranking.ranking import (
        _gather_tournament_context,
        _matchup_debate_turns,
        _median_elo,
    )

    wave = plan.wave
    judge_context = _WaveJudgeContext(
        state, _gather_tournament_context(state), plan.index
    )
    median = _median_elo(eligible)
    depths = [_matchup_debate_turns(pair[0], pair[1], median) for pair in wave]
    judged = await asyncio.gather(
        *(
            _judge_one_matchup(pair, offset, judge_context, depths[offset])
            for offset, pair in enumerate(wave)
        ),
        return_exceptions=True,
    )
    return _surviving_judgements(wave, list(judged), depths)


def _apply_wave_elo(
    wave: list[Any],
    judged: list[tuple[str, dict[str, Any]]],
    depths: list[int],
    state: dict[str, Any],
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Apply a judged wave's Elo updates in wave order.

    Elo is applied in wave order so the committed result is independent of
    the order the concurrent judgements happened to return in.

    ``depths`` is what each matchup was *budgeted*; a debate that reached a
    decided majority early spends fewer turns than that, and reports the
    turns it actually judged on the response. Metering the budget instead
    would charge the run's LLM allowance for calls it never made, and
    ``max_llm_calls`` is a termination bound -- over-counting it shortens
    runs for no reason.
    """
    from co_scientist.agents.ranking.ranking import (
        _apply_matchup_elo,
        _build_matchup_detail,
    )
    from co_scientist.constants import ELO_K_FACTOR

    k_factor = int(state.get("elo_k_factor") or ELO_K_FACTOR)
    # Read once per wave: every matchup in it is judged in the same cycle,
    # and the detail is the only place the cycle is still known (the drain
    # persists every cycle's accumulated matchups together at the end).
    iteration = int(state.get("current_iteration", 0))
    details: list[dict[str, Any]] = []
    total_calls = 0
    last_pair: list[str] = []
    for offset, (pair, (winner, response)) in enumerate(
        zip(wave, judged, strict=True)
    ):
        hypothesis_a, hypothesis_b = pair
        outcome = _apply_matchup_elo(
            hypothesis_a,
            hypothesis_b,
            winner,
            k_factor=k_factor,
            # Feeds only the margin-scaling reconstruction knob (off by
            # default), so it is inert unless that knob is enabled.
            confidence=response.get("confidence_level"),
        )
        details.append(
            _build_matchup_detail(pair, winner, response, outcome, iteration)
        )
        total_calls += int(response.get("debate_turns", depths[offset]))
        last_pair = [hypothesis_a.id, hypothesis_b.id]
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
        survived.pairs, survived.judgements, survived.depths, state
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
