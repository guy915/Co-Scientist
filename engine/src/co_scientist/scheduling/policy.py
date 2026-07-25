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

from collections.abc import Callable

from co_scientist.scheduling.models import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    TerminationReason,
)
from co_scientist.scheduling.policy_checks import (
    _budget_termination,
    _check_convergence,
    _check_iteration_budget,
    _check_owed_coverage,
    _check_pool_size,
    _check_proximity_refresh,
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
    "_check_owed_coverage",
    "_check_pool_size",
    "_check_proximity_refresh",
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
    """Builds the precedence-ordered scheduling checks (steps 1-11)."""
    return (
        lambda: _check_stop_signals(stats),
        lambda: _check_steering(stats),
        lambda: _check_owed_coverage(stats),
        lambda: _budget_termination(stats, budget),
        lambda: _check_retry(stats),
        lambda: _check_review_backlog(stats),
        lambda: _check_pool_size(stats, budget),
        lambda: _check_tournament_coverage(stats, min_match_coverage),
        lambda: _check_proximity_refresh(stats),
        lambda: _check_convergence(
            stats, convergence_cycles, min_cycles_before_convergence
        ),
        lambda: _check_iteration_budget(stats, budget),
    )


def required_transition(
    stats: SchedulerStats,
    budget: Budget,
    *,
    min_match_coverage: float = MIN_MATCH_COVERAGE_DEFAULT,
    convergence_cycles: int = CONVERGENCE_CYCLES_DEFAULT,
    min_cycles_before_convergence: int = MIN_CYCLES_BEFORE_CONVERGENCE_DEFAULT,
) -> SupervisorDecision | None:
    """Return the forced decision when one of steps 1-11 fires, else None.

    Separates the two halves of :func:`decide_next_task`. Steps 1-11 are
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
    11 (see each check's docstring), and finally the generation-vs-evolution
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
