"""Carry task history and settlement allowances between scheduling decisions."""

from __future__ import annotations

from typing import Any

from co_scientist.agents.ranking.ranking_lifecycle import _coverage_floor
from co_scientist.agents.reflection.owed_review import (
    mark_owed_review_issued,
    owed_review_targets,
)
from co_scientist.agents.supervisor.orchestrator_stats import _default_budget
from co_scientist.models import Hypothesis
from co_scientist.scheduling import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    policy,
    stacked_task_values,
)
from co_scientist.state import WorkflowState


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
