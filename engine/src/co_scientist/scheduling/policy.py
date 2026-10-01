"""Deterministic Supervisor scheduling policy.

:func:`decide_next_task` is a pure function of :class:`SchedulerStats` and a
:class:`Budget`. Given the observable state at a loop point, it returns the
next :class:`SupervisorDecision` — which task to run (or to terminate, and
why). The policy is deterministic and order-independent so the required
scheduling states can be tested in isolation.

An LLM Supervisor may *recommend* a next task; :func:`validate_decision` is the
gate that enforces the allowed transitions and budget on any recommendation
before the graph acts on it — the code decides, the model only advises.

Where Google does not publish a predicate (the exact convergence test, the
minimum match coverage), the value here is a documented clone default; see the
``*_DEFAULT`` constants and the ``CLONE`` rows in ``docs/PARITY.md``.

The individual predicates live in :mod:`co_scientist.scheduling.policy_checks`
and the decision validation in
:mod:`co_scientist.scheduling.policy_corrections`; both are re-exported here so
this module remains the single import surface for the policy. What stays here
is :func:`_ordered_checks` — the precedence itself, which is the feature.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from co_scientist.scheduling.models import (
    ENQUEUE_ACTION,
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    TerminationReason,
    stacked_task_values,
)
from co_scientist.scheduling.policy_checks import (
    _budget_termination,
    _check_convergence,
    _check_iteration_budget,
    _check_meta_review_cadence,
    _check_owed_coverage,
    _check_owed_review,
    _check_pool_size,
    _check_proximity_refresh,
    _check_research_overview_cadence,
    _check_retry,
    _check_review_backlog,
    _check_steering,
    _check_stop_signals,
    _check_tournament_coverage,
    _evolve,
    _generate,
    _generation_vs_evolution,
    _terminate,
)
from co_scientist.scheduling.policy_corrections import (
    ALLOWED_LOOP_TASKS,
    _correct_disallowed_task,
    _correct_evolve_precondition,
    _correct_for_steering,
    _correct_rank_precondition,
    validate_decision,
)

# Re-exported so ``co_scientist.scheduling.policy`` keeps the exact namespace
# it had before the checks and corrections moved to sibling modules. Callers
# (notably ``agents.supervisor.orchestrator``, which calls
# ``policy._check_owed_coverage`` directly) import from here.
__all__ = [
    "ALLOWED_LOOP_TASKS",
    "CONVERGENCE_CYCLES_DEFAULT",
    "MIN_CYCLES_BEFORE_CONVERGENCE_DEFAULT",
    "MIN_MATCH_COVERAGE_DEFAULT",
    "Budget",
    "SchedulerStats",
    "SupervisorDecision",
    "TaskType",
    "TerminationReason",
    "_budget_termination",
    "_check_convergence",
    "_check_iteration_budget",
    "_check_meta_review_cadence",
    "_check_owed_coverage",
    "_check_owed_review",
    "_check_pool_size",
    "_check_proximity_refresh",
    "_check_research_overview_cadence",
    "_check_retry",
    "_check_review_backlog",
    "_check_steering",
    "_check_stop_signals",
    "_check_tournament_coverage",
    "_correct_disallowed_task",
    "_correct_evolve_precondition",
    "_correct_for_steering",
    "_correct_rank_precondition",
    "_evolve",
    "_generate",
    "_generation_vs_evolution",
    "_ordered_checks",
    "_terminate",
    "decide_next_task",
    "required_transition",
    "stack_companions",
    "stacked_task_values",
    "validate_decision",
]

# --- Clone-defined scheduling thresholds (Google-unspecified) --------------

# Minimum average tournament matches per hypothesis before the scheduler stops
# asking for more ranking rounds. Keeps every hypothesis minimally calibrated.
MIN_MATCH_COVERAGE_DEFAULT = 1.0

# Number of consecutive cycles the top-of-leaderboard Elo must be unchanged
# (with no backlog and no pending growth) before the run is declared converged.
CONVERGENCE_CYCLES_DEFAULT = 2

# Minimum work cycles before convergence may fire. Two guarantees the system
# has both evolved leaders and generated into new regions (the loop alternates)
# before it is allowed to declare a stable leaderboard terminal — otherwise a
# stable first tournament could stop the run before it explores.
MIN_CYCLES_BEFORE_CONVERGENCE_DEFAULT = 2


def _ordered_checks(
    stats: SchedulerStats,
    budget: Budget,
    min_match_coverage: float,
    convergence_cycles: int,
    min_cycles_before_convergence: int,
) -> tuple[Callable[[], SupervisorDecision | None], ...]:
    """Builds the precedence-ordered scheduling checks (steps 1-13)."""
    return (
        lambda: _check_stop_signals(stats),
        lambda: _check_steering(stats),
        lambda: _check_owed_coverage(stats),
        lambda: _check_owed_review(stats, budget),
        lambda: _budget_termination(stats, budget),
        lambda: _check_retry(stats),
        lambda: _check_review_backlog(stats),
        lambda: _check_pool_size(stats, budget),
        lambda: _check_tournament_coverage(stats, min_match_coverage),
        lambda: _check_proximity_refresh(stats),
        lambda: _check_meta_review_cadence(stats),
        lambda: _check_convergence(
            stats, convergence_cycles, min_cycles_before_convergence
        ),
        lambda: _check_iteration_budget(stats, budget),
        # Below both terminations, unlike meta-review's cadence above them:
        # a critique is consumed by the terminal report, so it is worth
        # holding a run open for, while an interim overview is consumed by
        # the *next* generate cycle. Fired on the iteration that ends the
        # run it would buy the largest prompt in the system for a reader
        # that never arrives. Kept here as a step of its own even though
        # ``stack_companions`` now also runs this branch as a companion:
        # a companion never rides a terminating decision, so this
        # placement below both terminations is exactly what preserves
        # that rule rather than being made redundant by it.
        lambda: _check_research_overview_cadence(stats, budget),
    )


def required_transition(
    stats: SchedulerStats,
    budget: Budget,
    *,
    min_match_coverage: float = MIN_MATCH_COVERAGE_DEFAULT,
    convergence_cycles: int = CONVERGENCE_CYCLES_DEFAULT,
    min_cycles_before_convergence: int = MIN_CYCLES_BEFORE_CONVERGENCE_DEFAULT,
) -> SupervisorDecision | None:
    """Return the forced decision when one of steps 1-13 fires, else None.

    Separates the two halves of :func:`decide_next_task`. Steps 1-13 are
    *required* transitions: an unreviewed backlog must be reviewed, a pool
    of one cannot hold a tournament, a spent budget must stop. There is no
    latitude in them, so an advisory model has nothing to contribute and
    every guard would overrule it anyway.

    Only the generation-vs-evolution fall-through is a genuine judgement
    call. Exposing the split lets a caller skip a planning round-trip on
    the forced majority and spend one only where the choice is open.

    Returns:
        The forced decision, or None when the choice is open.
    """
    for check in _ordered_checks(
        stats,
        budget,
        min_match_coverage,
        convergence_cycles,
        min_cycles_before_convergence,
    ):
        decision = check()
        if decision is not None:
            return decision
    return None


def decide_next_task(
    stats: SchedulerStats,
    budget: Budget,
    *,
    min_match_coverage: float = MIN_MATCH_COVERAGE_DEFAULT,
    convergence_cycles: int = CONVERGENCE_CYCLES_DEFAULT,
    min_cycles_before_convergence: int = MIN_CYCLES_BEFORE_CONVERGENCE_DEFAULT,
) -> SupervisorDecision:
    """Choose the next task (or terminate) from observable state.

    The precedence, highest first, is exactly ``_ordered_checks``'s steps 1-
    13 (see each check's docstring), and finally the generation-vs-evolution
    choice. ``min_match_coverage``, ``convergence_cycles``, and
    ``min_cycles_before_convergence`` are clone defaults where Google does
    not publish a predicate.

    Returns:
        The scheduler's decision, always carrying a recorded reason.
    """
    forced = required_transition(
        stats,
        budget,
        min_match_coverage=min_match_coverage,
        convergence_cycles=convergence_cycles,
        min_cycles_before_convergence=min_cycles_before_convergence,
    )
    if forced is not None:
        return forced

    # Generation vs evolution by relative yield.
    return _generation_vs_evolution(stats)


# The one primary that carries no companion at all: ``terminate`` gates the
# task record's status, the termination reason written to state, and every
# ``_hard_stop``/``validate_decision`` short-circuit above -- and a run that
# is stopping has no next cycle left to read a companion's output.
_UNSTACKABLE_TASKS = frozenset({TaskType.TERMINATE})

# For each companion, the primaries it is not stacked onto. Two reasons,
# both about the meta_review node: a primary that already runs a companion's
# own node would run it twice (META_REVIEW and EVOLVE both enter at
# meta_review, ``workflow_topology.TASK_ROUTES``; SYNTHESIZE *is* the
# research_overview node), and the overview is drafted *from* the critique,
# so stacking it ahead of a primary that is about to write one would invert
# the listing's own order on that pass. Deferring it costs nothing: the
# cadence anchor only resets when the firing is actually scheduled.
_COMPANION_CONFLICTS: dict[TaskType, frozenset[TaskType]] = {
    TaskType.META_REVIEW: frozenset({TaskType.META_REVIEW, TaskType.EVOLVE}),
    TaskType.SYNTHESIZE: frozenset(
        {TaskType.SYNTHESIZE, TaskType.META_REVIEW, TaskType.EVOLVE}
    ),
}


def _due_companions(
    stats: SchedulerStats, budget: Budget
) -> tuple[SupervisorDecision, ...]:
    """Return the listing's periodic branches that are due, in its order.

    ``GenerateSystemFeedback`` (L61-64) before
    ``GenerateFinalResearchOverview`` (L65-69), which is also the order
    they need: the overview is drafted from the critique the feedback
    pass has just synthesized.

    These two are the whole stackable set. The listing's other branches
    are its unconditional ``RunTournamentBatch`` and its evolve ``IF``,
    and neither can be a companion here: both are multi-node chains whose
    fixed successor is the loop point itself (``rank -> safety_screen ->
    ... -> ranking -> orchestrator``, ``evolve -> meta_review -> evolve
    -> review -> ... -> orchestrator``), so a companion form of either
    could not hand control back to the primary -- in this topology they
    *are* the primary. Both also advance work the counters key on, and a
    ranking wave costs 4-12 judged multi-turn debates against these
    two's one call each.
    """
    checks = (
        _check_meta_review_cadence(stats),
        _check_research_overview_cadence(stats, budget),
    )
    return tuple(check for check in checks if check is not None)


def stack_companions(
    decision: SupervisorDecision, stats: SchedulerStats, budget: Budget
) -> SupervisorDecision:
    """Attach the follow-up tasks one pass may queue alongside its own.

    Listing 01's ``DecideNextSteps`` queues several tasks from one pass --
    one unconditional statement and three *independent* ``IF``s -- while
    ``_ordered_checks`` is a single-winner precedence chain, so whichever
    branch wins suppresses the rest. This restores the independence of
    the two periodic branches (``_due_companions``) by riding the
    decision's existing ``queue_actions``, which already travel with it
    through the orchestrator's own commit transaction.

    Deliberately *additive*: ``next_task`` is untouched, because the
    settlement allowance (``orchestrator_bookkeeping._is_settlement_rank``),
    the iteration counter (``orchestrator._advance_iteration``) and the
    yield attribution all key on it, and a wrap that renamed the primary
    would silently unbound the settlement episode. The companions are an
    *ordering*, resolved by the loop-point router: they run first, in this
    order, and the primary behind them. Serial rather than parallel
    because the durable checkpoint chain has one writer per commit -- two
    rows anchored to the same predecessor would fork it, and only the head
    of a serial chain is ever claimable.

    Args:
        decision: The primary decision the precedence chain settled on.
        stats: The statistics that decision was made from.
        budget: The run's budget, which gates the overview companion by
            tier exactly as it gates that branch's own standalone step.

    Returns:
        ``decision``, with the due companions appended to its queue
        actions, and unchanged when none is due.
    """
    if decision.terminate or decision.next_task in _UNSTACKABLE_TASKS:
        return decision
    actions = tuple(
        {
            "action": ENQUEUE_ACTION,
            "task_type": companion.next_task.value,
            "reason": companion.reason,
        }
        for companion in _due_companions(stats, budget)
        if decision.next_task not in _COMPANION_CONFLICTS[companion.next_task]
    )
    if not actions:
        return decision
    return dataclasses.replace(
        decision, queue_actions=(*decision.queue_actions, *actions)
    )
