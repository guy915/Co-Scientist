"""Observable statistics the orchestrator hands the scheduling policy.

Derives the scalars a scheduling decision reads -- pool and review counts,
rankable match coverage, yields attributed to the last work task, Elo
stability, and the run's compute budget -- from workflow state plus the
orchestrator's carried bookkeeping. The decision node, its bookkeeping, and
the settlement allowance stay in ``orchestrator.py`` and
``orchestrator_bookkeeping.py``; ``orchestrator.py`` re-exports these names
for compatibility.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any

from co_scientist.agents.ranking.ranking_lifecycle import (
    _coverage_floor,
    _tournament_round_count,
)
from co_scientist.constants import INITIAL_ELO_RATING
from co_scientist.llm_call_budget import current_run_call_count
from co_scientist.models import Hypothesis, has_peer_review
from co_scientist.scheduling import (
    Budget,
    SchedulerStats,
    TaskType,
)
from co_scientist.state import WorkflowState


@dataclasses.dataclass(frozen=True)
class _StatsScalars:
    """The observable scalars derived from state for one scheduler decision."""

    pool_size: int
    reviewed: int
    rankable_count: int
    total_matches: int
    avg_coverage: float
    unmatched_rankable_count: int
    owed_coverage_rounds: int
    top_elo: int
    llm_calls: int
    gen_yield: float
    evo_yield: float
    elapsed_s: float


def _default_budget(state: WorkflowState) -> Budget:
    """Return the run's compute budget, or one derived from max_iterations.

    A run may configure a full budget via ``state["budget"]``; otherwise the
    only ceiling is the existing ``max_iterations`` satisfied-completion cap.
    """
    raw = state.get("budget")
    if raw:
        return Budget.from_dict(raw)
    return Budget(max_iterations=state.get("max_iterations", 0))


def _yields(pool_size: int, book: dict[str, Any]) -> tuple[float, float]:
    """Return (generation_yield, evolution_yield) from the pool delta.

    The delta since the previous decision is attributed to whichever work task
    ran last: new rows after a GENERATE are generation yield, appended children
    after an EVOLVE are evolution yield. A yield is a simple count of net new
    hypotheses (0 when the last task was maintenance such as proximity).
    """
    delta = max(
        0, pool_size - int(book.get("pool_at_last_decision", pool_size))
    )
    last = book.get("last_work_task")
    if last == TaskType.GENERATE.value:
        return float(delta), 0.0
    if last == TaskType.EVOLVE.value:
        return 0.0, float(delta)
    return 0.0, 0.0


def _rank_stable_cycles(
    top_elo: int, total_matches: int, book: dict[str, Any]
) -> int:
    """Return the updated count of consecutive stable-leaderboard cycles.

    Stability requires at least one match to have been played (an untouched
    initial pool is not "converged") and the top Elo to be unchanged from the
    previous decision. The seeded ``prev_top_elo`` of None (first decision) is
    never stable — there is no prior cycle to compare against.
    """
    prev = book.get("prev_top_elo")
    prior = int(book.get("rank_stable_cycles", 0))
    if total_matches > 0 and prev is not None and top_elo == int(prev):
        return prior + 1
    return 0


def _compute_stats(
    state: WorkflowState, book: dict[str, Any]
) -> SchedulerStats:
    """Derive the scheduler's observable statistics from workflow state.

    Args:
        state: Current workflow state.
        book: Orchestrator bookkeeping from before this decision.

    Returns:
        The statistics the deterministic policy reads.
    """
    hyps: list[Hypothesis] = state["hypotheses"]
    pool_size = len(hyps)
    rankable_count, avg_coverage, unmatched = _rankable_coverage(hyps)
    llm_calls, gen_yield, evo_yield, elapsed_s = _scheduler_scalars(
        state, book, pool_size
    )
    scalars = _StatsScalars(
        pool_size=pool_size,
        reviewed=sum(1 for h in hyps if has_peer_review(h)),
        rankable_count=rankable_count,
        total_matches=sum(h.total_matches for h in hyps),
        avg_coverage=avg_coverage,
        unmatched_rankable_count=unmatched,
        # The tournament's own floor over this pool, so the settlement
        # episode the scheduler opens and the rounds it may spend are one
        # number rather than two that agree only at the extremes.
        owed_coverage_rounds=_coverage_floor(hyps),
        top_elo=max((h.elo_rating for h in hyps), default=INITIAL_ELO_RATING),
        llm_calls=llm_calls,
        gen_yield=gen_yield,
        evo_yield=evo_yield,
        elapsed_s=elapsed_s,
    )
    return _build_scheduler_stats(state, book, scalars)


def _rankable_coverage(
    hyps: list[Hypothesis],
) -> tuple[int, float, int]:
    """Return (rankable_count, average coverage, unmatched count).

    Coverage is measured over the rankable pool only. An un-rankable idea
    (one a review or the evidence gate rejected) can never accrue matches,
    so counting it in the denominator would hold average coverage below the
    gate forever and loop the orchestrator on ranking. Deep-verification
    "undermined" ideas *are* counted: they rank, so they accrue matches and
    belong in both halves of the fraction.

    The unmatched count is reported separately because the average cannot
    represent it: a pool can clear its average threshold while individual
    hypotheses have never been matched at all.

    Args:
        hyps: The full hypothesis pool.

    Returns:
        The rankable count, their average match coverage, and how many of
        them have never been matched.
    """
    rankable = [h for h in hyps if h.is_rankable()]
    rankable_count = len(rankable)
    rankable_matches = sum(h.total_matches for h in rankable)
    avg_coverage = rankable_matches / rankable_count if rankable_count else 0.0
    # Reported beside ``owed_coverage_rounds`` in the same decision, so it
    # is counted over the same population: an idea still owing the run a
    # peer review is owed that review rather than matches (see
    # ``ranking_lifecycle._coverage_floor``). Reading the two off different
    # populations is what would let the reason line say an idea has never
    # been matched while the floor it quotes says nothing is owed.
    unmatched = sum(
        1 for h in rankable if h.total_matches == 0 and has_peer_review(h)
    )
    return rankable_count, avg_coverage, unmatched


def _scheduler_scalars(
    state: WorkflowState, book: dict[str, Any], pool_size: int
) -> tuple[int, float, float, float]:
    """Return (llm_calls, generation_yield, evolution_yield, elapsed_s).

    ``llm_calls`` reads the seam-counted total (``llm_call_budget``,
    incremented once per actual provider request regardless of which node
    made it) rather than the self-reported ``metrics.llm_calls``: a dozen
    nodes never reported into the metric at all, so it structurally
    under-counted and let ``max_llm_calls`` see spend that never happened.
    ``max()`` with the self-reported figure covers the one case the seam
    cannot see on its own -- a process restart resets its in-memory
    counter to zero while a resumed run's checkpoint still carries the
    (still merely non-decreasing) self-reported count, so falling back to
    zero would let a resumed run spend a second full budget.
    """
    metrics = state.get("metrics")
    reported = metrics.llm_calls if metrics is not None else 0
    run_id = state.get("run_id")
    seam_count = current_run_call_count(run_id) if run_id else 0
    llm_calls = max(seam_count, reported)
    gen_yield, evo_yield = _yields(pool_size, book)
    start = state.get("start_time") or time.time()
    return llm_calls, gen_yield, evo_yield, time.time() - start


def _meta_review_gap(
    book: dict[str, Any], scalars: _StatsScalars, iteration: int
) -> tuple[int, int]:
    """Return (work cycles, critique material) since the last meta-review.

    Both are differences against anchors the orchestrator's bookkeeping
    reset the last time a decision routed through the meta_review node
    (``orchestrator_bookkeeping._meta_review_anchors``). Floored at zero
    because proximity dedup removes hypotheses and their match tallies with
    them, so the material total is not strictly monotone.
    """
    cycles = iteration - int(book.get("iteration_at_last_meta_review", 0))
    material = (scalars.reviewed + scalars.total_matches) - int(
        book.get("feedback_at_last_meta_review", 0)
    )
    return max(0, cycles), max(0, material)


def _cadence_signals(
    state: WorkflowState,
    book: dict[str, Any],
    scalars: _StatsScalars,
    pool_size: int,
    iteration: int,
) -> dict[str, Any]:
    """Bundle the since-last-checkpoint cadence fields the policy reads.

    Each measures progress against a bookkeeping anchor the orchestrator
    reset the last time a decision routed through the corresponding node
    (proximity, ranking stability, meta-review) -- see
    ``orchestrator_bookkeeping.py``.
    """
    meta_cycles, meta_material = _meta_review_gap(book, scalars, iteration)
    return {
        "pool_grew_since_proximity": (
            pool_size > int(book.get("pool_at_last_proximity", pool_size))
        ),
        "rank_stable_cycles": _rank_stable_cycles(
            scalars.top_elo, scalars.total_matches, book
        ),
        "iterations_since_meta_review": meta_cycles,
        "feedback_since_meta_review": meta_material,
        # Same shape as the meta-review clock beside it, with no material
        # counter: a periodic overview synthesizes the pool itself, and a
        # completed work cycle has by definition changed it (FIX-6).
        "iterations_since_research_overview": max(
            0,
            iteration - int(book.get("iteration_at_last_research_overview", 0)),
        ),
        "evolved_since_stable": bool(book.get("evolved_since_stable", False)),
    }


def _build_scheduler_stats(
    state: WorkflowState,
    book: dict[str, Any],
    scalars: _StatsScalars,
) -> SchedulerStats:
    """Assembles the SchedulerStats value object from computed scalars."""
    pool_size = scalars.pool_size
    iteration = state.get("current_iteration", 0)
    cadence = _cadence_signals(state, book, scalars, pool_size, iteration)
    return SchedulerStats(
        pool_size=pool_size,
        reviewed_count=scalars.reviewed,
        unreviewed_count=pool_size - scalars.reviewed,
        rankable_count=scalars.rankable_count,
        total_matches=scalars.total_matches,
        match_coverage=scalars.avg_coverage,
        unmatched_rankable_count=scalars.unmatched_rankable_count,
        owed_coverage_rounds=scalars.owed_coverage_rounds,
        settlement_allowance=book.get("settlement_allowance"),
        owed_at_last_settlement=book.get("owed_at_last_settlement"),
        tournament_rounds_remaining=_tournament_round_count(
            state, state.get("hypotheses") or []
        ),
        top_elo=scalars.top_elo,
        generation_yield=scalars.gen_yield,
        evolution_yield=scalars.evo_yield,
        iteration=iteration,
        last_work_task=_task_type_or_none(book.get("last_work_task")),
        llm_calls=scalars.llm_calls,
        tasks_run=len(state.get("task_history", [])),
        elapsed_s=scalars.elapsed_s,
        pending_steering=bool(state.get("pending_steering")),
        cancelled=bool(state.get("cancel_requested")),
        safety_blocked=bool(state.get("safety_blocked")),
        **cadence,
    )


def _task_type_or_none(value: Any) -> TaskType | None:
    """Coerce a stored task-type string back to its enum, or None."""
    if value is None:
        return None
    return TaskType(value)
