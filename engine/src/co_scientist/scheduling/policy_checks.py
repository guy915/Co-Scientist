"""Precedence-ordered scheduling checks for the Supervisor policy.

Each ``_check_*`` (plus :func:`_budget_termination`) is a pure predicate over
:class:`SchedulerStats` and :class:`Budget` that either returns the decision it
forces or ``None`` to defer to the next check. The order in which they are
consulted is the feature, and it lives in ``policy._ordered_checks``; nothing
here may assume or impose an order of its own.

:func:`_generation_vs_evolution` is the fall-through used once every required
transition has declined.
"""

from __future__ import annotations

from co_scientist.scheduling.models import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    TerminationReason,
)
from co_scientist.scheduling.policy_budget import (
    _terminate as _terminate,
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
    vs. evolution*. A clear yield edge decides directly; a tie defers to
    :func:`_tie_break`, which is strictly stagnation-gated rather than
    alternating blind.
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
    return _tie_break(stats, can_evolve)


def _tie_break(stats: SchedulerStats, can_evolve: bool) -> SupervisorDecision:
    """Break a generate/evolve yield tie on measured leaderboard stagnation.

    Evolution earns the tie only on the *transition* into stagnation --
    ``rank_stable_cycles >= 1`` and the last work task was not already an
    evolve -- not on standing stagnation. ``rank_stable_cycles`` does not
    reset once the leaderboard settles; it stays >= 1 for every subsequent
    cycle until the Elo ordering next changes. Evolving on the bare level
    condition would therefore evolve every remaining tie for the rest of the
    run, breeding the evolution pool from an already-converged set of
    survivors on each pass -- the same narrowing failure mode already seen
    in production (repeated evolution of a stagnant pool converges on
    near-identical descendants). Requiring ``last_work_task`` not to already
    be EVOLVE makes the trigger fire once per stagnation episode: the first
    stagnant tie evolves, and the very next tie -- stagnant or not --
    generates instead, exploring a new region rather than re-breeding a
    leaderboard that evolution has already had one uncontested attempt to
    move. This also covers the common both-zero tie, including the seeded
    first decision where ``rank_stable_cycles`` starts at 0 because no match
    has been played yet, so evolution never fires on a tie without evidence
    the leaderboard has actually settled.
    """
    just_evolved = stats.last_work_task is TaskType.EVOLVE
    if can_evolve and stats.rank_stable_cycles >= 1 and not just_evolved:
        return _evolve(
            f"yield tie (gen=evo={stats.generation_yield:.2f}) on the "
            f"transition into a stagnant leaderboard "
            f"({stats.rank_stable_cycles} stable cycle(s)); evolve leaders"
        )
    if stats.rank_stable_cycles >= 1:
        return _generate(
            f"yield tie (gen=evo={stats.generation_yield:.2f}) with a "
            "leaderboard still stagnant after evolution already had its "
            "turn; generate new regions instead of re-breeding it"
        )
    return _generate(
        f"yield tie (gen=evo={stats.generation_yield:.2f}) with no measured "
        "leaderboard stagnation; generate new regions"
    )


def _check_stop_signals(stats: SchedulerStats) -> SupervisorDecision | None:
    """Step 1: an external safety stop wins outright.

    Cancellation is not checked here: the durable executor enforces it by
    never dispatching another node once a run is marked cancelled, so there
    is no graph-internal signal for this policy to read (see
    ``TerminationReason``'s docstring).
    """
    if stats.safety_blocked:
        return _terminate(
            TerminationReason.SAFETY, "safety block halted the run"
        )
    return None


def _check_owed_coverage(
    stats: SchedulerStats,
) -> SupervisorDecision | None:
    """Step 3: settle hypotheses the tournament still owes matches to.

    Ranked above the budget ceilings and below the safety stop and scientist
    steering. A hypothesis that leaves a run under-covered has no tournament
    result worth reading, which is a worse outcome than a small, bounded
    overshoot of a ceiling that exists to catch runaways rather than to
    meter work. A safety block still wins outright: the content is unsafe,
    and more work is wrong regardless of coverage. Steering wins because the
    orchestrator consumes a steering message on the cycle it observes it, so
    losing that cycle to ranking would drop the scientist's message
    entirely.

    Per-hypothesis rather than the average used by
    :func:`_check_tournament_coverage`, which cannot represent this state:
    35 hypotheses at two matches each averages 1.46 across 48 and clears a
    1.0 threshold while 13 have never been matched once.

    Triggers on ``owed_coverage_rounds`` -- the tournament's own coverage
    floor -- and not on the zero-match count, because that count is coarser
    than the episode it opens. The episode is *sized* from the floor, so a
    trigger that only saw ideas with no match at all could never let the
    size apply: ten ideas each at one match of the two the tournament asks
    for owe five rounds and report zero unmatched, and the run ended
    under-covered while this check reported coverage satisfied. The floor is
    the stricter test -- an idea with no matches always owes rounds -- so
    this subsumes the old trigger rather than replacing it.

    Bounded by ``settlement_allowance``, which is scoped to a settlement
    *episode*: within one it strictly decreases and is never refilled, so an
    episode fires finitely many times, and a new episode can begin only once
    the owed rounds reached zero -- that is, only once settlement succeeded.
    The run therefore always reaches a terminal decision. That argument needs
    the episode to open and close on the *same* quantity: a close measured on
    a coarser count than the trigger would re-arm the allowance while this
    check still fired, refilling the very counter that bounds it. The bound
    is otherwise structural: it does not assume ranking makes progress, that
    pairings remain, or that the pool holds still. The stall test below is a
    cost optimisation on top of it, not the thing that makes the loop safe.
    """
    if stats.owed_coverage_rounds < 1:
        return None
    # Nothing to pair against: demanding coverage could never be satisfied.
    if stats.rankable_count < 2:
        return None
    allowance = stats.settlement_allowance
    if allowance is not None and allowance < 1:
        return None
    previous = stats.owed_at_last_settlement
    if previous is not None and stats.owed_coverage_rounds >= previous:
        return None
    return SupervisorDecision(
        next_task=TaskType.RANK,
        reason=(
            f"{stats.owed_coverage_rounds} tournament round(s) owed to bring "
            "every rankable idea to minimum coverage "
            f"({stats.unmatched_rankable_count} have never been matched); "
            "settle coverage before terminating"
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
    """Step 11: stable leaderboard with no outstanding work.

    Only fires after enough work cycles that the loop has both evolved and
    generated.

    Gated additionally on ``evolved_since_stable``: listing 01 L55-58
    answers a leaderboard that has stopped improving with *evolution*, not
    with a stop, so a run may not terminate on stagnation it has never
    tried to break. ``_tie_break`` grants that attempt on the transition
    into stagnation, and this waits for it. The wait is bounded, not open:
    when it holds, this check simply defers, and ``_check_iteration_budget``
    directly below still terminates the run at ``max_iterations``.
    """
    if not stats.evolved_since_stable:
        return None
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
    """Step 12: satisfied iteration budget."""
    if stats.iteration >= budget.max_iterations:
        return _terminate(
            TerminationReason.COMPLETED,
            f"reached iteration budget ({stats.iteration}/"
            f"{budget.max_iterations})",
        )
    return None
