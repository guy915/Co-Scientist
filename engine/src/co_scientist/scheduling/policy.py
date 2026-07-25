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

# Task types the compiled graph's loop-point router can dispatch. META_REVIEW
# is reached as the head of the EVOLVE branch; SYNTHESIZE is the TERMINATE
# target. Keep in sync with the graph's conditional edges.
ALLOWED_LOOP_TASKS: frozenset[TaskType] = frozenset(
    {
        TaskType.GENERATE,
        TaskType.REFLECT,
        TaskType.RANK,
        TaskType.EVOLVE,
        TaskType.PROXIMITY,
        TaskType.TERMINATE,
    }
)


def _budget_termination(
    stats: SchedulerStats, budget: Budget
) -> SupervisorDecision | None:
    """Return a termination decision if any hard budget ceiling is hit.

    Checked before any productive task so an exhausted run always stops with a
    precise, recorded reason rather than scheduling more work it cannot afford.
    """
    max_calls = budget.max_llm_calls
    if max_calls is not None and stats.llm_calls >= max_calls:
        return _terminate(
            TerminationReason.BUDGET,
            f"LLM-call budget exhausted ({stats.llm_calls}/{max_calls})",
        )
    if budget.max_tasks is not None and stats.tasks_run >= budget.max_tasks:
        return _terminate(
            TerminationReason.MAX_TASKS,
            f"task budget exhausted ({stats.tasks_run}/{budget.max_tasks})",
        )
    if (
        budget.max_wall_clock_s is not None
        and stats.elapsed_s >= budget.max_wall_clock_s
    ):
        return _terminate(
            TerminationReason.WALL_CLOCK,
            f"wall-clock budget exhausted ({stats.elapsed_s:.0f}s/"
            f"{budget.max_wall_clock_s:.0f}s)",
        )
    return None


def _terminate(reason: TerminationReason, message: str) -> SupervisorDecision:
    """Build a terminating decision with a recorded reason."""
    return SupervisorDecision(
        next_task=TaskType.TERMINATE,
        reason=message,
        terminate=True,
        termination_reason=reason,
    )


def _evolve(reason: str) -> SupervisorDecision:
    """Build an EVOLVE decision."""
    return SupervisorDecision(next_task=TaskType.EVOLVE, reason=reason)


def _generate(reason: str) -> SupervisorDecision:
    """Build a GENERATE decision."""
    return SupervisorDecision(next_task=TaskType.GENERATE, reason=reason)


def _generation_vs_evolution(stats: SchedulerStats) -> SupervisorDecision:
    """Choose GENERATE vs EVOLVE from the relative yields (Supervisor §4).

    The paper's Supervisor weights the *relative effectiveness of generation
    vs. evolution*. A clear yield edge decides directly. On a tie (including
    the common both-zero case), alternate off the last work task so later
    cycles still explore new regions rather than only ever evolving — the
    first loop after the initial generation evolves the leaders, and the cycle
    after that generates into unexplored space.
    """
    gen_y, evo_y = stats.generation_yield, stats.evolution_yield
    can_evolve = stats.reviewed_count >= 2
    if evo_y > gen_y and can_evolve:
        return _evolve(
            f"evolution out-yields generation (evo={evo_y:.2f} > "
            f"gen={gen_y:.2f}); evolve leaders"
        )
    if gen_y > evo_y:
        return _generate(
            f"generation out-yields evolution (gen={gen_y:.2f} > "
            f"evo={evo_y:.2f}); generate new regions"
        )
    # Tie: alternate off the last work task to keep exploring.
    if stats.last_work_task is TaskType.EVOLVE:
        return _generate(
            "alternating after evolution; generate unexplored regions"
        )
    if can_evolve:
        return _evolve("alternating after generation; evolve leaders")
    return _generate("too few reviewed leaders to evolve; generate")


def _check_stop_signals(stats: SchedulerStats) -> SupervisorDecision | None:
    """Step 1: external stop signals (cancellation, safety) win outright."""
    if stats.cancelled:
        return _terminate(TerminationReason.CANCELLED, "run cancelled")
    if stats.safety_blocked:
        return _terminate(
            TerminationReason.SAFETY, "safety block halted the run"
        )
    return None


def _check_owed_coverage(
    stats: SchedulerStats,
) -> SupervisorDecision | None:
    """Step 3: settle hypotheses that have never entered the tournament.

    Ranked above the budget ceilings and below the cancel/safety stops and
    scientist steering. A hypothesis that leaves a run unmatched has no
    tournament result at all, which is a worse outcome than a small,
    bounded overshoot of a ceiling that exists to catch runaways rather
    than to meter work. Cancellation and safety blocks still win outright:
    the operator asked to stop, or the content is unsafe, and more work is
    wrong in both cases. Steering wins because the orchestrator consumes a
    steering message on the cycle it observes it, so losing that cycle to
    ranking would drop the scientist's message entirely.

    Per-hypothesis rather than the average used by
    :func:`_check_tournament_coverage`, which cannot represent this state:
    35 hypotheses at two matches each averages 1.46 across 48 and clears a
    1.0 threshold while 13 have never been matched once.

    Bounded by ``settlement_allowance``, which is scoped to a settlement
    *episode*: within one it strictly decreases and is never refilled, so an
    episode fires finitely many times, and a new episode can begin only once
    the backlog reached zero -- that is, only once settlement succeeded. The
    run therefore always reaches a terminal decision. That bound is
    structural: it does not assume ranking makes progress, that pairings
    remain, or that the pool holds still. The stall test below is a cost
    optimisation on top of it, not the thing that makes the loop safe.
    """
    if stats.unmatched_rankable_count < 1:
        return None
    # Nothing to pair against: demanding coverage could never be satisfied.
    if stats.rankable_count < 2:
        return None
    allowance = stats.settlement_allowance
    if allowance is not None and allowance < 1:
        return None
    previous = stats.unmatched_at_last_settlement
    if previous is not None and stats.unmatched_rankable_count >= previous:
        return None
    return SupervisorDecision(
        next_task=TaskType.RANK,
        reason=(
            f"{stats.unmatched_rankable_count} hypothesis(es) have no "
            "tournament matches; settle coverage before terminating"
        ),
    )


def _check_retry(stats: SchedulerStats) -> SupervisorDecision | None:
    """Step 4: retry a failed task before scheduling new work."""
    if stats.last_task_failed is not None and stats.retries_remaining > 0:
        return SupervisorDecision(
            next_task=stats.last_task_failed,
            reason=(
                f"retrying failed task {stats.last_task_failed.value} "
                f"({stats.retries_remaining} retries remaining)"
            ),
        )
    return None


def _check_steering(stats: SchedulerStats) -> SupervisorDecision | None:
    """Step 2: user steering is a high-priority request to explore anew.

    Carries the same priority as ``_correct_for_steering``: a scientist's
    steering must outrank queued work whether it was reached by the
    scheduler directly or by correcting a model allocation away from it.

    Above :func:`_check_owed_coverage` because ``orchestrator_node`` clears
    ``pending_steering`` on the cycle it observes it: a message that loses
    its cycle to a settlement round is marked applied with no work scheduled
    to incorporate it, so it is dropped outright. Owed coverage must in turn
    stay above the budget ceilings, so this placement also puts steering
    above them -- a pending message buys one cycle on an exhausted budget.
    That is intended: the scientist asked for it explicitly, and steering is
    one-shot, so it cannot repeat.
    """
    if stats.pending_steering:
        return SupervisorDecision(
            next_task=TaskType.GENERATE,
            reason="pending user steering; generate to incorporate it",
            priority=100,
        )
    return None


def _check_review_backlog(
    stats: SchedulerStats,
) -> SupervisorDecision | None:
    """Step 5: review the backlog before ranking or evolving unreviewed work."""
    if stats.unreviewed_count > 0:
        return SupervisorDecision(
            next_task=TaskType.REFLECT,
            reason=(
                f"{stats.unreviewed_count} unreviewed hypotheses; review "
                "before ranking"
            ),
        )
    return None


def _check_pool_size(
    stats: SchedulerStats, budget: Budget
) -> SupervisorDecision | None:
    """Step 6: a tournament needs at least two hypotheses.

    Honors the iteration ceiling here too: if generation keeps failing to
    grow the pool past one hypothesis, each GENERATE still advances the
    iteration counter, so without this the run would loop until the graph's
    recursion limit raised GraphRecursionError instead of terminating with a
    recorded reason. (The resource ceilings are already enforced above; only
    the iteration ceiling sits below this branch, so only it needs handling
    here.)
    """
    if stats.pool_size >= 2:
        return None
    if stats.iteration >= budget.max_iterations:
        return _terminate(
            TerminationReason.COMPLETED,
            f"pool too small to continue ({stats.pool_size}) and "
            f"iteration budget reached ({stats.iteration}/"
            f"{budget.max_iterations})",
        )
    return SupervisorDecision(
        next_task=TaskType.GENERATE,
        reason=(
            f"pool too small for a tournament ({stats.pool_size}); "
            "generate more"
        ),
    )


def _check_tournament_coverage(
    stats: SchedulerStats, min_match_coverage: float
) -> SupervisorDecision | None:
    """Step 7: ensure minimum tournament coverage / calibration.

    Only when at least two hypotheses are rankable; otherwise there is
    nothing to rank and demanding coverage would loop the orchestrator
    forever (a pool of evidence-gate-rejected ideas can never accrue
    matches).

    The run's tournament budget is the same kind of guard. Coverage is a
    property of the pool and may never reach its threshold, so once the
    budget is spent ranking can no longer move it -- asking again would
    schedule a task that returns immediately, forever.
    """
    remaining = stats.tournament_rounds_remaining
    if remaining is not None and remaining < 1:
        return None
    if stats.rankable_count >= 2 and stats.match_coverage < min_match_coverage:
        return SupervisorDecision(
            next_task=TaskType.RANK,
            reason=(
                f"avg match coverage {stats.match_coverage:.2f} below "
                f"{min_match_coverage:.2f}; run more tournament rounds"
            ),
        )
    return None


def _check_proximity_refresh(
    stats: SchedulerStats,
) -> SupervisorDecision | None:
    """Step 8: refresh proximity when the pool grew (dedup + matchmaking)."""
    if stats.pool_grew_since_proximity:
        return SupervisorDecision(
            next_task=TaskType.PROXIMITY,
            reason="pool grew since last proximity; refresh clustering",
        )
    return None


def _check_convergence(
    stats: SchedulerStats,
    convergence_cycles: int,
    min_cycles_before_convergence: int,
) -> SupervisorDecision | None:
    """Step 9: stable leaderboard with no outstanding work.

    Only fires after enough work cycles that the loop has both evolved and
    generated.
    """
    if (
        stats.iteration >= min_cycles_before_convergence
        and stats.rank_stable_cycles >= convergence_cycles
    ):
        return _terminate(
            TerminationReason.CONVERGED,
            f"top-ranked Elo stable for {stats.rank_stable_cycles} cycles",
        )
    return None


def _check_iteration_budget(
    stats: SchedulerStats, budget: Budget
) -> SupervisorDecision | None:
    """Step 10: satisfied iteration budget."""
    if stats.iteration >= budget.max_iterations:
        return _terminate(
            TerminationReason.COMPLETED,
            f"reached iteration budget ({stats.iteration}/"
            f"{budget.max_iterations})",
        )
    return None


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


def _correct_for_steering(
    task: TaskType, stats: SchedulerStats
) -> SupervisorDecision | None:
    """Pending scientist steering reprioritizes fresh generation."""
    if stats.pending_steering and task is not TaskType.GENERATE:
        return SupervisorDecision(
            next_task=TaskType.GENERATE,
            reason=(
                "corrected: scientist steering reprioritized fresh generation"
            ),
            priority=100,
        )
    return None


def _correct_disallowed_task(
    task: TaskType, stats: SchedulerStats
) -> SupervisorDecision | None:
    """A task outside ``ALLOWED_LOOP_TASKS`` is not dispatchable."""
    if task not in ALLOWED_LOOP_TASKS:
        return SupervisorDecision(
            next_task=TaskType.GENERATE,
            reason=f"corrected: {task.value} is not a dispatchable loop task",
        )
    return None


def _correct_rank_precondition(
    task: TaskType, stats: SchedulerStats
) -> SupervisorDecision | None:
    """RANK requires at least two rankable hypotheses; otherwise GENERATE."""
    if task == TaskType.RANK and stats.rankable_count < 2:
        return SupervisorDecision(
            next_task=TaskType.GENERATE,
            reason=(
                "corrected: fewer than two rankable hypotheses "
                f"({stats.rankable_count}); generate instead of looping on rank"
            ),
        )
    return None


def _correct_evolve_precondition(
    task: TaskType, stats: SchedulerStats
) -> SupervisorDecision | None:
    """EVOLVE needs a reviewed hypothesis; otherwise REFLECT or GENERATE."""
    if task == TaskType.EVOLVE and stats.reviewed_count < 1:
        fallback = (
            TaskType.REFLECT
            if stats.unreviewed_count > 0
            else TaskType.GENERATE
        )
        return SupervisorDecision(
            next_task=fallback,
            reason=(
                "corrected: cannot evolve with no reviewed hypotheses; "
                f"{fallback.value}"
            ),
        )
    return None


def validate_decision(
    decision: SupervisorDecision, stats: SchedulerStats
) -> SupervisorDecision:
    """Enforce allowed transitions on a (possibly LLM-recommended) decision.

    The code — not the model — validates. A decision that violates a
    precondition is downgraded to a safe alternative rather than executed;
    see each ``_correct_*`` helper for its specific precondition.

    Args:
        decision: The proposed decision (from :func:`decide_next_task` or an
            LLM Supervisor recommendation).
        stats: The statistics the decision must be consistent with.

    Returns:
        The original decision, or a corrected safe one, with the reason
        annotated when it was changed.
    """
    if decision.terminate:
        return decision

    task = decision.next_task
    for correct in (
        _correct_for_steering,
        _correct_disallowed_task,
        _correct_rank_precondition,
        _correct_evolve_precondition,
    ):
        corrected = correct(task, stats)
        if corrected is not None:
            return corrected
    return decision
