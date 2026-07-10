"""Deterministic Supervisor scheduling policy.

:func:`decide_next_task` is a pure function of :class:`SchedulerStats` and a
:class:`Budget`. Given the observable state at a loop point, it returns the
next :class:`SupervisorDecision` — which task to run (or to terminate, and
why). The policy is deterministic and order-independent so the required
scheduling states can be tested in isolation (PLAN.md M2.3).

An LLM Supervisor may *recommend* a next task; :func:`validate_decision` is the
gate that enforces the allowed transitions and budget on any recommendation
before the graph acts on it — the code decides, the model only advises.

Where Google does not publish a predicate (the exact convergence test, the
minimum match coverage), the value here is a documented clone default; see the
``*_DEFAULT`` constants and the ``CLONE`` rows in ``docs/PARITY.md``.
"""

from __future__ import annotations

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


def decide_next_task(
    stats: SchedulerStats,
    budget: Budget,
    *,
    min_match_coverage: float = MIN_MATCH_COVERAGE_DEFAULT,
    convergence_cycles: int = CONVERGENCE_CYCLES_DEFAULT,
    min_cycles_before_convergence: int = MIN_CYCLES_BEFORE_CONVERGENCE_DEFAULT,
) -> SupervisorDecision:
    """Choose the next task (or terminate) from observable state.

    The precedence, highest first: external stop signals (cancellation,
    safety), hard budget ceilings, retry of a failed task, user steering,
    review backlog, minimum pool for a tournament, tournament coverage,
    proximity refresh, convergence, satisfied iteration budget, and finally
    the generation-vs-evolution choice.

    Args:
        stats: Observable statistics computed from the workflow state.
        budget: Compute budget and its termination limits.
        min_match_coverage: Minimum avg matches/hypothesis before ranking is
            considered sufficient (clone default).
        convergence_cycles: Stable-Elo cycles before declaring convergence
            (clone default).
        min_cycles_before_convergence: Minimum work cycles before convergence
            may fire, so the loop evolves and generates at least once first
            (clone default).

    Returns:
        The scheduler's decision, always carrying a recorded reason.
    """
    # 1. External stop signals win outright.
    if stats.cancelled:
        return _terminate(TerminationReason.CANCELLED, "run cancelled")
    if stats.safety_blocked:
        return _terminate(
            TerminationReason.SAFETY, "safety block halted the run"
        )

    # 2. Hard budget ceilings.
    budget_stop = _budget_termination(stats, budget)
    if budget_stop is not None:
        return budget_stop

    # 3. Retry a failed task before scheduling new work.
    if stats.last_task_failed is not None and stats.retries_remaining > 0:
        return SupervisorDecision(
            next_task=stats.last_task_failed,
            reason=(
                f"retrying failed task {stats.last_task_failed.value} "
                f"({stats.retries_remaining} retries remaining)"
            ),
        )

    # 4. User steering is a high-priority request to explore anew.
    if stats.pending_steering:
        return SupervisorDecision(
            next_task=TaskType.GENERATE,
            reason="pending user steering; generate to incorporate it",
        )

    # 5. Review the backlog before ranking or evolving unreviewed work.
    if stats.unreviewed_count > 0:
        return SupervisorDecision(
            next_task=TaskType.REFLECT,
            reason=(
                f"{stats.unreviewed_count} unreviewed hypotheses; review "
                "before ranking"
            ),
        )

    # 6. A tournament needs at least two hypotheses. Honor the iteration
    # ceiling here too: if generation keeps failing to grow the pool past one
    # hypothesis, each GENERATE still advances the iteration counter, so
    # without this the run would loop until the graph's recursion limit raised
    # GraphRecursionError instead of terminating with a recorded reason. (The
    # resource ceilings are already enforced above; only the iteration ceiling
    # sits below this branch, so only it needs handling here.)
    if stats.pool_size < 2:
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

    # 7. Ensure minimum tournament coverage / calibration.
    if stats.match_coverage < min_match_coverage:
        return SupervisorDecision(
            next_task=TaskType.RANK,
            reason=(
                f"avg match coverage {stats.match_coverage:.2f} below "
                f"{min_match_coverage:.2f}; run more tournament rounds"
            ),
        )

    # 8. Refresh proximity when the pool grew (dedup + matchmaking input).
    if stats.pool_grew_since_proximity:
        return SupervisorDecision(
            next_task=TaskType.PROXIMITY,
            reason="pool grew since last proximity; refresh clustering",
        )

    # 9. Convergence: stable leaderboard with no outstanding work, but only
    # after enough work cycles that the loop has both evolved and generated.
    if (
        stats.iteration >= min_cycles_before_convergence
        and stats.rank_stable_cycles >= convergence_cycles
    ):
        return _terminate(
            TerminationReason.CONVERGED,
            f"top-ranked Elo stable for {stats.rank_stable_cycles} cycles",
        )

    # 10. Satisfied iteration budget.
    if stats.iteration >= budget.max_iterations:
        return _terminate(
            TerminationReason.COMPLETED,
            f"reached iteration budget ({stats.iteration}/"
            f"{budget.max_iterations})",
        )

    # 11. Generation vs evolution by relative yield.
    return _generation_vs_evolution(stats)


def validate_decision(
    decision: SupervisorDecision, stats: SchedulerStats
) -> SupervisorDecision:
    """Enforce allowed transitions on a (possibly LLM-recommended) decision.

    The code — not the model — validates. A decision that violates a
    precondition is downgraded to a safe alternative rather than executed:

    - RANK requires at least two hypotheses; otherwise GENERATE.
    - EVOLVE requires at least one reviewed hypothesis; otherwise, if there is
      a review backlog, REFLECT, else GENERATE.
    - A non-terminate task outside ``ALLOWED_LOOP_TASKS`` is not dispatchable;
      fall back to GENERATE.

    Args:
        decision: The proposed decision (from :func:`decide_next_task` or an
            LLM Supervisor recommendation).
        stats: The statistics the decision must be consistent with.

    Returns:
        The original decision, or a corrected safe one, with the reason
        annotated when it was changed.
    """
    task = decision.next_task
    if decision.terminate:
        return decision

    if task not in ALLOWED_LOOP_TASKS:
        return SupervisorDecision(
            next_task=TaskType.GENERATE,
            reason=f"corrected: {task.value} is not a dispatchable loop task",
        )
    if task == TaskType.RANK and stats.pool_size < 2:
        return SupervisorDecision(
            next_task=TaskType.GENERATE,
            reason="corrected: cannot rank a pool smaller than 2; generate",
        )
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
    return decision
