"""Supervisor routing, cycle bookkeeping and observable scheduler statistics."""

from __future__ import annotations

import dataclasses
import logging
import time
from typing import Any

from co_scientist.agents.ranking.ranking_lifecycle import (
    _coverage_floor,
    _tournament_round_count,
)
from co_scientist.agents.reflection.owed_review import (
    mark_owed_review_issued,
    owed_review_targets,
)
from co_scientist.agents.reflection.owed_review import (
    owed_review_count as _owed_review_count,
)
from co_scientist.agents.supervisor.supervisor_decision import (
    WORK_TASKS,
    choose_supervisor_task,
)
from co_scientist.constants import (
    INITIAL_ELO_RATING,
    PROGRESS_ORCHESTRATOR_DECISION,
)
from co_scientist.llm import current_run_call_count
from co_scientist.models import (
    Hypothesis,
    MetricDeltas,
    create_metrics_update,
    has_peer_review,
    phase_message,
)
from co_scientist.progress import emit_progress
from co_scientist.scheduling import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskRecord,
    TaskStatus,
    TaskType,
    policy,
    stacked_task_values,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class _StatsScalars:
    """The observable scalars derived from state for one scheduler decision."""

    pool_size: int
    reviewed: int
    owed_review: int
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
        owed_review=_owed_review_count(hyps),
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

    ``llm_calls`` reads the seam-counted total (``llm.admission.call_budget``,
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
        owed_review_count=scalars.owed_review,
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
        # Default True so a state assembled before this field existed (or a
        # restored checkpoint from one) keeps meta-review on.
        meta_review_enabled=state.get("enable_meta_review", True) is not False,
        **cadence,
    )


def _task_type_or_none(value: Any) -> TaskType | None:
    """Coerce a stored task-type string back to its enum, or None."""
    if value is None:
        return None
    return TaskType(value)


def _init_bookkeeping(hypotheses: list[Hypothesis]) -> dict[str, Any]:
    """Seed orchestrator bookkeeping on the first loop-point decision.

    Anchors the pool sizes to the post-initial-generation pool so the first
    decision sees no proximity backlog and a yield tie — which, with the last
    work task treated as the initial GENERATE, evolves the leaders first
    (matching the established first-iteration behavior) before later cycles
    alternate into generation.
    """
    pool_size = len(hypotheses)
    return {
        # Sentinel so the first decision's Elo comparison never counts as
        # "stable" (there is no prior cycle to be stable against).
        "prev_top_elo": None,
        "rank_stable_cycles": 0,
        "pool_at_last_proximity": pool_size,
        "pool_at_last_decision": pool_size,
        "last_work_task": TaskType.GENERATE.value,
        # None until a settlement episode opens: the override may fire, and
        # the allowance is sized from the backlog observed at that moment.
        # Both fields return to None whenever the backlog clears.
        "settlement_allowance": None,
        "owed_at_last_settlement": None,
        # Meta-review cadence anchors. Zero rather than the pool's current
        # counts so the first firing is gated by the iteration clock alone:
        # the initial generation's reviews are exactly the material the
        # first system-wide feedback should be synthesized from.
        "iteration_at_last_meta_review": 0,
        "feedback_at_last_meta_review": 0,
        # The periodic research overview's own cadence anchor (FIX-6),
        # seeded the same way and read by _research_overview_anchor below.
        "iteration_at_last_research_overview": 0,
        # No evolve has run yet, and no leaderboard has settled yet either.
        "evolved_since_stable": False,
    }


# Tasks that route through the meta_review node, so scheduling either one
# resets the cadence anchors (``workflow_topology.TASK_ROUTES``).
_META_REVIEW_ROUTED_TASKS = frozenset({TaskType.META_REVIEW, TaskType.EVOLVE})

# Tasks that advance the iteration counter as they are scheduled; mirrors
# ``orchestrator._advance_iteration``'s own rule.
_ITERATION_ADVANCING_TASKS = frozenset({TaskType.GENERATE, TaskType.EVOLVE})


def _routes_through_meta_review(decision: SupervisorDecision) -> bool:
    """Whether this decision runs the meta_review node before it is done.

    Three ways it can: the task *is* meta-review, the task is EVOLVE (whose
    route enters at meta_review so the critique feeds the evolution
    prompts), or the pass stacked meta-review as a companion ahead of some
    other primary (``policy.stack_companions``). All three consume the
    critique material accumulated so far, so all three re-anchor the
    cadence -- a stacked firing that did not would re-stack on every
    remaining loop point.
    """
    if decision.next_task in _META_REVIEW_ROUTED_TASKS:
        return True
    return TaskType.META_REVIEW.value in stacked_task_values(
        decision.queue_actions
    )


def _schedules_research_overview(decision: SupervisorDecision) -> bool:
    """Whether this decision runs the overview node before it is done.

    Two ways it can, exactly as ``_routes_through_meta_review`` above: the
    task *is* the periodic overview, or the pass stacked that same branch
    as a companion ahead of some other primary. Both consume the cadence,
    so both must re-anchor it -- a stacked firing that did not would
    re-stack on every remaining loop point.
    """
    if decision.next_task is TaskType.SYNTHESIZE:
        return True
    return TaskType.SYNTHESIZE.value in stacked_task_values(
        decision.queue_actions
    )


def _research_overview_anchor(
    book: dict[str, Any],
    stats: SchedulerStats,
    decision: SupervisorDecision,
) -> int:
    """Return the iteration anchor the periodic overview's cadence reads.

    Unchanged unless this decision schedules a periodic overview firing;
    when it does, the anchor is the current iteration. No "the iteration
    the decision becomes" adjustment, unlike ``_meta_review_anchors``
    below: that adjustment exists because EVOLVE both routes through the
    meta_review node and advances the counter, and SYNTHESIZE does
    neither. Resetting the anchor as the decision is taken is what
    terminates the step -- the overview is not a work task, so nothing
    else would ever move the gap off its threshold.
    """
    if not _schedules_research_overview(decision):
        return int(book.get("iteration_at_last_research_overview", 0))
    return stats.iteration


def _feedback_total(stats: SchedulerStats) -> int:
    """Return the critique material meta-review synthesizes from.

    Reviews written plus tournament participations played: exactly the two
    inputs ``GenerateSystemFeedback`` gathers (listing 07 L12). Read as one
    monotone-ish total rather than two counters because the cadence only
    ever asks whether *any* of it is new.
    """
    return stats.reviewed_count + stats.total_matches


def _meta_review_anchors(
    book: dict[str, Any],
    stats: SchedulerStats,
    decision: SupervisorDecision,
) -> tuple[int, int]:
    """Return the (iteration, feedback) cadence anchors for the next decision.

    Unchanged unless this decision routes through the meta_review node.
    When it does, the iteration anchor is the iteration the decision
    *becomes*, not the one its stats were read at: ``orchestrator.
    _advance_iteration`` increments the counter for a work task as it is
    scheduled, so anchoring at the pre-increment value would read as a
    completed cycle on the very next decision and buy a second firing it
    had not earned.
    """
    if not _routes_through_meta_review(decision):
        return (
            int(book.get("iteration_at_last_meta_review", 0)),
            int(book.get("feedback_at_last_meta_review", 0)),
        )
    advanced = 1 if decision.next_task in _ITERATION_ADVANCING_TASKS else 0
    return stats.iteration + advanced, _feedback_total(stats)


def _evolved_since_stable(
    book: dict[str, Any], stats: SchedulerStats, decision: SupervisorDecision
) -> bool:
    """Return whether evolution has answered the current stagnation episode.

    Set when an EVOLVE is scheduled against a leaderboard that has already
    settled (``rank_stable_cycles >= 1``), and cleared the moment the
    ordering moves again, so each fresh stagnation episode earns its own
    evolve attempt before ``policy_checks._check_convergence`` may call the
    run done. An evolve scheduled *before* anything settled does not count:
    listing 01 L55-58's response is to the stagnation, and a stale flag from
    an earlier cycle would let the very next settling terminate untried.
    """
    if stats.rank_stable_cycles < 1:
        return False
    if decision.next_task is TaskType.EVOLVE:
        return True
    return bool(book.get("evolved_since_stable", False))


def _is_settlement_rank(
    stats: SchedulerStats, decision: SupervisorDecision
) -> bool:
    """Return whether this decision is a ranking round that settles coverage.

    Re-derived by running the policy's own owed-coverage check against the
    same stats rather than inferred from ``next_task``: a RANK is a
    settlement round only when that check asked for one. Inferring it from
    "RANK while anything is unmatched" charged ordinary calibration ranking
    to the allowance, which drained an episode before it began.

    The check is a pure function of ``stats`` with no I/O, so re-running it
    is exact and cheap, and the policy stays free of any settlement state of
    its own.
    """
    return (
        decision.next_task is TaskType.RANK
        and policy._check_owed_coverage(stats) is not None
    )


def _is_owed_review_override(stats: SchedulerStats, budget: Budget) -> bool:
    """Return whether ``_check_owed_review`` is asking for a pass this cycle.

    Deliberately *not* re-derived from the decision actually taken, unlike
    ``_is_settlement_rank`` above: on the queue-adjudication path
    (``supervisor_decision._needs_queue_adjudication``) a consulted model
    may return a task other than REFLECT even though this check supplied
    the forced baseline, and marking on the *executed* task would leave
    that cycle's override neither spent nor bounded -- the same next-cycle
    ``stats.owed_review_count`` would ask for it again, with nothing
    changed about why the model diverted the first time. Marking on
    whether the check *fired*, independent of what got executed, is what
    keeps the bound in ``policy_checks._check_owed_review`` -- at most
    ``owed_review.MAX_OWED_REVIEW_OVERRIDES_PER_RUN`` firings ever -- true
    regardless of planner behavior. The cost is symmetric with
    ``review_recheck``'s own bound: a hypothesis marked this way whose
    forced review never actually ran is in the same state as one whose
    forced review ran and failed -- one spent attempt, no peer review.
    """
    return policy._check_owed_review(stats, budget) is not None


def _owed_review_override_marks(
    stats: SchedulerStats, budget: Budget, hypotheses: list[Hypothesis]
) -> list[Hypothesis]:
    """Return the pool to persist after this cycle's override marking.

    Marks every hypothesis currently owed the override at once, before the
    forced review's own outcome is known (mirroring
    ``review_recheck.mark_recheck_issued``): the marker records that this
    hypothesis's one budget-overriding attempt has been *spent*, not that
    it *succeeded*, which is what stops a hypothesis whose review keeps
    failing -- or whose forced cycle a consulted model diverted away from
    (see ``_is_owed_review_override``) -- from re-arming
    ``_check_owed_review`` on every remaining cycle.

    Returns ``[]`` -- "no update" under
    ``state.reducers.deduplicate_hypotheses`` -- when the check did not
    fire this cycle, so a caller may include this in every decision's
    state delta unconditionally. Returns the *full* pool (mutated in
    place), never a subset, when it did: the reducer's bare-list form
    replaces the pool with exactly what it is given, and a partial list
    would silently drop the rest of the pool from the run.
    """
    if not _is_owed_review_override(stats, budget):
        return []
    for hypothesis in owed_review_targets(hypotheses):
        mark_owed_review_issued(hypothesis)
    return hypotheses


def _owed_review_hypotheses_delta(
    state: WorkflowState, stats: SchedulerStats
) -> list[Hypothesis]:
    """Return the ``hypotheses`` entry of the orchestrator's state delta.

    "no update" (an empty list) unless ``_check_owed_review`` is asking
    for a pass this cycle, in which case the currently-owed
    hypotheses are marked before the forced review's own outcome --
    or whether it even runs -- is known (see
    ``_owed_review_override_marks``).
    """
    budget = _default_budget(state)
    return _owed_review_override_marks(stats, budget, state["hypotheses"])


def _initial_settlement_allowance(hypotheses: list[Hypothesis]) -> int:
    """Return the most settlement rounds that could ever be useful.

    Delegates to ``ranking_lifecycle._coverage_floor`` rather than restating
    it: one round covers at most two owed matches and the pool admits only so
    many distinct pairings, which is the same arithmetic over the same pool
    that bounds the rounds an individual tournament schedules.

    A near-copy that read the scheduler's zero-match count instead agreed with
    the floor only at the extremes. The floor sums what each rankable idea
    still owes against ``TOURNAMENT_MIN_MATCHES_PER_HYPOTHESIS``, so ten ideas
    sitting at one match each owed the tournament five rounds and the
    orchestrator none -- and the orchestrator's is the number that decides how
    long settlement may run.

    ``SchedulerStats.owed_coverage_rounds`` is this same floor computed from
    the same pool one layer up, which is what lets the episode open, close,
    and be sized on a single quantity.
    """
    return _coverage_floor(hypotheses)


def _settled_allowance(
    book: dict[str, Any],
    stats: SchedulerStats,
    decision: SupervisorDecision,
    hypotheses: list[Hypothesis],
) -> tuple[int | None, int | None]:
    """Return the (allowance, last-owed) pair for the next decision.

    The allowance is scoped to a *settlement episode*, not to the run. An
    episode opens on the first round the owed-coverage check requests and
    closes when the owed rounds reach zero, at which point both fields return
    to None so a later backlog re-arms from what it actually owes.

    Within an episode the counter is initialised once, is charged on every
    settlement round whether or not the round helped, floors at zero, and is
    never increased -- so an episode fires finitely often. A new episode can
    open only after the owed rounds reached zero, which is to say only after
    settlement succeeded, so the run still reaches a terminal decision.

    Trigger, close, and size are one quantity: the tournament's coverage
    floor over the pool, read here as ``stats.owed_coverage_rounds`` and
    recomputed as the initial allowance. They were briefly two -- the
    scheduler asked whether any rankable idea had *no* match at all while the
    size counted every match still owed -- and that split is what let a pool
    sitting one match short of the minimum end a run under-covered. Closing
    on a coarser quantity than the trigger is the more dangerous half of the
    same mistake: the episode would re-arm while the check still fired,
    refilling the allowance that bounds it, and the settlement loop would
    have nothing left to stop it.
    """
    if _is_settlement_rank(stats, decision):
        allowance = book.get("settlement_allowance")
        if allowance is None:
            allowance = _initial_settlement_allowance(hypotheses)
        return (
            max(0, int(allowance) - 1),
            stats.owed_coverage_rounds,
        )
    if stats.owed_coverage_rounds == 0:
        # Episode over: nothing is owed, so the counter re-arms.
        return None, None
    return (
        book.get("settlement_allowance"),
        book.get("owed_at_last_settlement"),
    )


def _next_bookkeeping(
    book: dict[str, Any],
    stats: SchedulerStats,
    decision: SupervisorDecision,
    hypotheses: list[Hypothesis],
) -> dict[str, Any]:
    """Compute the bookkeeping to carry into the next decision.

    Updates the rank-stability counter and previous top Elo, resets the
    proximity anchor after a proximity task, remembers the pool size and the
    last *work* task (generate/evolve) so the next decision can measure yield
    and break ties, and advances the settlement-episode allowance that bounds
    how long owed tournament coverage may override a budget ceiling (see
    :func:`_settled_allowance`).

    Args:
        book: Orchestrator bookkeeping from before this decision.
        stats: The statistics this decision was made from.
        decision: The scheduling decision just taken.
        hypotheses: The pool ``stats`` was computed from, read for the
            tournament coverage a fresh settlement episode is sized from.

    Returns:
        The bookkeeping to carry into the next decision.
    """
    updated = dict(book)
    updated["prev_top_elo"] = stats.top_elo
    updated["rank_stable_cycles"] = stats.rank_stable_cycles
    updated["pool_at_last_decision"] = stats.pool_size
    if decision.next_task is TaskType.PROXIMITY:
        updated["pool_at_last_proximity"] = stats.pool_size
    if decision.next_task in (TaskType.GENERATE, TaskType.EVOLVE):
        updated["last_work_task"] = decision.next_task.value
    allowance, last_owed = _settled_allowance(book, stats, decision, hypotheses)
    updated["settlement_allowance"] = allowance
    updated["owed_at_last_settlement"] = last_owed
    meta_iteration, meta_feedback = _meta_review_anchors(book, stats, decision)
    updated["iteration_at_last_meta_review"] = meta_iteration
    updated["feedback_at_last_meta_review"] = meta_feedback
    updated["iteration_at_last_research_overview"] = _research_overview_anchor(
        book, stats, decision
    )
    updated["evolved_since_stable"] = _evolved_since_stable(
        book, stats, decision
    )
    return updated


@dataclasses.dataclass(frozen=True)
class _DecisionOutcome:
    """One scheduling decision plus its derived recording fields."""

    decision: SupervisorDecision
    decision_provenance: str
    iteration: int
    observable_reason: str
    termination_reason_value: str | None
    # Real LLM calls this decision spent -- 1 when the planner model was
    # consulted, 0 for a hard-stop or required transition (finding L3).
    llm_calls: int = 0


def _appended_task_record(
    state: WorkflowState,
    decision: SupervisorDecision,
    iteration: int,
    observable_reason: str,
) -> list[dict[str, Any]]:
    """Return task_history with this decision's record appended."""
    record = TaskRecord(
        task_type=decision.next_task,
        status=(
            TaskStatus.COMPLETED if decision.terminate else TaskStatus.QUEUED
        ),
        reason=observable_reason,
        iteration=iteration,
        termination_reason=decision.termination_reason,
    )
    history = list(state.get("task_history", []))
    serialized = record.to_dict()
    serialized["priority"] = decision.priority
    # The raw model rationale remains available for operator audit but is not
    # presented as a factual activity summary.
    serialized["planner_reason"] = decision.reason
    history.append(serialized)
    return history


def _observable_decision_reason(
    stats: SchedulerStats,
    decision: SupervisorDecision,
) -> str:
    """Describe an allocation using committed facts instead of model claims."""
    match_count = stats.total_matches // 2
    reason = (
        f"Supervisor selected {decision.next_task.value} from live state: "
        f"{stats.pool_size} hypotheses, {stats.reviewed_count} reviewed, "
        f"{match_count} committed matches, iteration {stats.iteration}."
    )
    if stats.pending_steering:
        reason += " Scientist feedback is pending incorporation."
    return reason


async def orchestrator_node(state: WorkflowState) -> dict[str, Any]:
    """Decide and record the next task at the adaptive loop point.

    Computes observable statistics, consults the deterministic policy
    (validated for allowed transitions), appends a task record with the
    decision's reason, emits a progress event, and sets ``next_task`` for the
    graph's conditional edge.

    Args:
        state: Current workflow state.

    Returns:
        State delta: ``next_task``, appended ``task_history``, updated
        ``orchestrator_state``, ``current_iteration`` (incremented on a work
        task), and ``termination_reason`` when terminating.
    """
    book = state.get("orchestrator_state") or _init_bookkeeping(
        state["hypotheses"]
    )
    (
        stats,
        decision,
        decision_provenance,
        llm_calls,
    ) = await _run_supervisor_decision(state, book)
    iteration, observable_reason, termination_reason_value = _decision_context(
        state, stats, decision
    )
    outcome = _DecisionOutcome(
        decision=decision,
        decision_provenance=decision_provenance,
        iteration=iteration,
        observable_reason=observable_reason,
        termination_reason_value=termination_reason_value,
        llm_calls=llm_calls,
    )
    return await _finalize_orchestrator_decision(state, book, stats, outcome)


async def _finalize_orchestrator_decision(
    state: WorkflowState,
    book: dict[str, Any],
    stats: SchedulerStats,
    outcome: _DecisionOutcome,
) -> dict[str, Any]:
    """Logs/streams the decision, then assembles the orchestrator_node delta."""
    await _emit_orchestrator_decision(state, outcome)
    return _orchestrator_result(state, book, stats, outcome)


async def _run_supervisor_decision(
    state: WorkflowState, book: dict[str, Any]
) -> tuple[SchedulerStats, SupervisorDecision, str, int]:
    """Computes scheduler stats and budget, then asks the policy to decide."""
    stats = _compute_stats(state, book)
    budget = _default_budget(state)
    decision, decision_provenance, llm_calls = await choose_supervisor_task(
        state, stats, budget
    )
    # Stacking runs after the primary is settled, never inside the policy:
    # the planner's own guards rebuild a decision with
    # ``dataclasses.replace(baseline, queue_actions=...)``, which would drop
    # a companion attached any earlier.
    return (
        stats,
        policy.stack_companions(decision, stats, budget),
        decision_provenance,
        llm_calls,
    )


def _advance_iteration(
    state: WorkflowState, decision: SupervisorDecision
) -> int:
    """Advances current_iteration for a work task; unchanged for maintenance.

    A work cycle (generate/evolve) advances the iteration counter; a
    maintenance task (proximity/rank/reflect) and termination do not.
    """
    iteration = state.get("current_iteration", 0)
    if decision.next_task in WORK_TASKS:
        iteration += 1
    return iteration


def _decision_context(
    state: WorkflowState, stats: SchedulerStats, decision: SupervisorDecision
) -> tuple[int, str, str | None]:
    """Derives the iteration, observable reason, and termination value."""
    iteration = _advance_iteration(state, decision)
    observable_reason = _observable_decision_reason(stats, decision)
    termination_reason_value = (
        decision.termination_reason.value
        if decision.termination_reason is not None
        else None
    )
    return iteration, observable_reason, termination_reason_value


async def _emit_orchestrator_decision(
    state: WorkflowState,
    outcome: _DecisionOutcome,
) -> None:
    """Logs and streams the scheduling decision."""
    decision = outcome.decision
    logger.info(
        "Orchestrator scheduled %s (iteration %s): %s",
        decision.next_task.value,
        outcome.iteration,
        outcome.observable_reason,
    )
    await emit_progress(
        state,
        "orchestrator_decision",
        outcome.observable_reason,
        PROGRESS_ORCHESTRATOR_DECISION,
        next_task=decision.next_task.value,
        termination_reason=outcome.termination_reason_value,
        decision_provenance=outcome.decision_provenance,
    )


def _orchestrator_result(
    state: WorkflowState,
    book: dict[str, Any],
    stats: SchedulerStats,
    outcome: _DecisionOutcome,
) -> dict[str, Any]:
    """Assembles the orchestrator_node state delta."""
    decision = outcome.decision
    return {
        "next_task": decision.next_task.value,
        "next_task_priority": decision.priority,
        "supervisor_queue_actions": list(decision.queue_actions),
        "task_history": _appended_task_record(
            state, decision, outcome.iteration, outcome.observable_reason
        ),
        "orchestrator_state": _next_bookkeeping(
            book, stats, decision, state["hypotheses"]
        ),
        "hypotheses": _owed_review_hypotheses_delta(state, stats),
        "supervisor_decision_provenance": outcome.decision_provenance,
        "current_iteration": outcome.iteration,
        # Steering is a one-shot high-priority request: clear it once the
        # orchestrator has seen it (and scheduled work to incorporate it) so
        # the loop does not re-trigger on the same message.
        "pending_steering": False,
        "termination_reason": outcome.termination_reason_value,
        "messages": phase_message(
            "orchestrator",
            outcome.observable_reason,
            next_task=decision.next_task.value,
        ),
        # finding L3: previously omitted, so a spent orchestrator planning
        # call never reached the accumulated llm_calls max_llm_calls reads.
        "metrics": create_metrics_update(
            deltas=MetricDeltas(llm_calls=outcome.llm_calls)
        ),
    }
