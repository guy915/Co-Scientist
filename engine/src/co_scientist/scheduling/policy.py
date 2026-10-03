"""The model can recommend tasks; deterministic checks enforce budget and
transition constraints; check order defines their precedence."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Final

from co_scientist.scheduling.models import (
    ENQUEUE_ACTION,
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    TerminationReason,
    stacked_task_values,
)


def _terminate(reason: TerminationReason, message: str) -> SupervisorDecision:
    """Build a terminating decision with a recorded reason."""
    return SupervisorDecision(
        next_task=TaskType.TERMINATE,
        reason=message,
        terminate=True,
        termination_reason=reason,
    )


def _llm_call_budget_check(
    stats: SchedulerStats, budget: Budget
) -> SupervisorDecision | None:
    """Terminate once the LLM-call ceiling is reached."""
    max_calls = budget.max_llm_calls
    if max_calls is None or stats.llm_calls < max_calls:
        return None
    return _terminate(
        TerminationReason.BUDGET,
        f"LLM-call budget exhausted ({stats.llm_calls}/{max_calls})",
    )


def _task_budget_check(
    stats: SchedulerStats, budget: Budget
) -> SupervisorDecision | None:
    """Terminate once the task ceiling is reached."""
    max_tasks = budget.max_tasks
    if max_tasks is None or stats.tasks_run < max_tasks:
        return None
    return _terminate(
        TerminationReason.MAX_TASKS,
        f"task budget exhausted ({stats.tasks_run}/{max_tasks})",
    )


def _wall_clock_budget_check(
    stats: SchedulerStats, budget: Budget
) -> SupervisorDecision | None:
    """Terminate once the wall-clock ceiling is reached."""
    limit = budget.max_wall_clock_s
    if limit is None or stats.elapsed_s < limit:
        return None
    return _terminate(
        TerminationReason.WALL_CLOCK,
        f"wall-clock budget exhausted ({stats.elapsed_s:.0f}s/{limit:.0f}s)",
    )


def _max_ideas_check(
    stats: SchedulerStats, budget: Budget
) -> SupervisorDecision | None:
    """Terminate once the idea-pool ceiling (paper's ``MaxIdeas``) is hit.

    Gated on ``unreviewed_count == 0``: this check runs before the review
    backlog step (``policy_checks._check_review_backlog``), so a bare
    pool-size ceiling would otherwise strand the freshest, still-unreviewed
    ideas at the moment the pool crosses it. Requiring the backlog drained
    first lets that step run on a later cycle before this one fires.
    """
    limit = budget.max_ideas
    if limit is None or stats.unreviewed_count > 0 or stats.pool_size < limit:
        return None
    return _terminate(
        TerminationReason.MAX_IDEAS,
        f"idea-pool budget exhausted ({stats.pool_size}/{limit})",
    )


def _max_matches_per_idea_check(
    stats: SchedulerStats, budget: Budget
) -> SupervisorDecision | None:
    """Terminate once coverage hits the paper's ``MaxMatchesPerIdea``.

    Measured on the same average-coverage observable
    ``policy_checks._check_tournament_coverage`` reads (``match_coverage``),
    not a true per-idea maximum -- see the ``Budget`` docstring for why.
    """
    limit = budget.max_matches_per_idea
    if (
        limit is None
        or stats.rankable_count < 2
        or stats.match_coverage < limit
    ):
        return None
    return _terminate(
        TerminationReason.MAX_MATCHES_PER_IDEA,
        f"match budget exhausted (avg {stats.match_coverage:.2f}/"
        f"{limit:.2f} matches per idea)",
    )


def _budget_termination(
    stats: SchedulerStats, budget: Budget
) -> SupervisorDecision | None:
    """Return a termination decision if any hard budget ceiling is hit.

    Checked before any productive task so an exhausted run always stops with a
    precise, recorded reason rather than scheduling more work it cannot afford.
    """
    for check in (
        _llm_call_budget_check,
        _task_budget_check,
        _wall_clock_budget_check,
        _max_ideas_check,
        _max_matches_per_idea_check,
    ):
        decision = check(stats, budget)
        if decision is not None:
            return decision
    return None


def _check_owed_review(
    stats: SchedulerStats, budget: Budget
) -> SupervisorDecision | None:
    """Force one review pass for a hypothesis the budget would drop unreviewed.

    Sits directly above ``_budget_termination``, mirroring
    ``policy_checks._check_owed_coverage`` immediately above it: a
    hypothesis admitted -- by generation, evolution, or a scientist's own
    contribution -- on the same cycle that exhausts the run's budget has no
    peer review at all, which is a worse outcome for the report than a
    small, bounded overshoot of a ceiling that exists to catch runaways
    rather than to meter work.

    Gated on the budget already being exhausted
    (``_budget_termination(stats, budget) is not None``), unlike
    ``_check_owed_coverage`` above it. That check's allowance re-arms
    itself once its settlement episode closes, so firing on every healthy
    cycle costs it nothing. This check's marker
    (``agents.reflection.owed_review``) is a permanent one-way door per
    hypothesis, so it must never fire outside the one scenario it exists
    for: firing on an ordinary, budget-healthy backlog REFLECT would spend
    a hypothesis's one override long before a genuinely budget-exhausting
    admission ever needed one, reopening exactly the window this check
    closes.

    Also refuses the one exhaustion reason it cannot safely override:
    ``TerminationReason.BUDGET`` (the LLM-call ceiling). That ceiling is
    enforced twice -- here, between scheduling decisions, and again
    *inside* a task by the provider-request seam
    (``llm.admission.call_budget.record_provider_request``), at the identical
    boundary: ``stats.llm_calls`` is read straight from that seam's own
    counter (``orchestrator_stats._scheduler_scalars``), and the app
    scopes the seam's ceiling from the same ``max_llm_calls`` run-config
    value ``Budget.max_llm_calls`` carries (``engine_tasks._llm_call_
    ceiling_for_run``, ``execute_engine_task``). The two boundaries do not
    just agree, they are the same number with zero headroom between them:
    the scheduler already terminates once ``llm_calls >= max_llm_calls``,
    and the seam raises on the very next request past that count. So a
    REFLECT dispatched to override this reason would make its first
    provider call straight into ``LLMCallBudgetExceededError`` -- one of
    the two *permanent* task failures (see ``app.task_worker``) -- turning
    a clean, BUDGET-terminated run into a failed one, which is strictly
    worse than the unreviewed idea this override exists to avoid. The
    override still buys a review against every other exhausted ceiling
    (task count, wall clock, idea-pool size, match coverage), none of
    which is enforced by an in-task seam that can raise mid-call.
    (``_check_owed_coverage`` shares this same latent hole for its own
    settlement RANK and is not changed here -- see the accompanying
    report.)

    Bounded, unlike owed coverage, by a simpler mechanism than an
    allowance: ``stats.owed_review_count`` already excludes every
    hypothesis that has had this override issued
    (``owed_review.owed_review_targets``), marked *before* the ensuing
    review's own outcome is known and capped run-wide
    (``owed_review.MAX_OWED_REVIEW_OVERRIDES_PER_RUN``). So a given
    hypothesis can make this count positive at most once ever, whether its
    forced review succeeds or fails -- there is no round-by-round
    allowance to track because there is nothing to retry: the override is
    spent the moment it fires, not the moment it succeeds. The count can
    only ever fall (a review lands, or the override is marked spent) or
    rise by a hypothesis newly joining the pool, which the run-wide cap
    still bounds regardless of how often that happens. A run therefore
    always reaches a terminal decision: this check can fire at most
    ``MAX_OWED_REVIEW_OVERRIDES_PER_RUN`` times before it is permanently
    exhausted.
    """
    termination = _budget_termination(stats, budget)
    if termination is None:
        return None
    if termination.termination_reason is TerminationReason.BUDGET:
        return None
    if stats.owed_review_count < 1:
        return None
    return SupervisorDecision(
        next_task=TaskType.REFLECT,
        reason=(
            f"{stats.owed_review_count} hypothesis(es) admitted but never "
            "reviewed; force one review pass before the budget can "
            "terminate the run"
        ),
    )


RESEARCH_OVERVIEW_MIN_LLM_CALLS: Final = 7000
"""Smallest declared run ceiling that funds a periodic overview firing.

Exactly the extended tier's ``max_llm_calls`` (``app.run_modes``), so the
gate reads "extended and ultra". Unlike meta-review's companion -- one
ordinary call -- the overview is the largest prompt in the system and the
caller most likely to climb the budget-escalation ladder, so a firing is
budgeted at one call plus up to two escalation retries. Express (1200)
runs a single iteration and would fire it before it had a second cycle to
feed; standard (2500) buys one extra cycle for it to feed, which is not
worth three calls at the overview's size.
"""

RESEARCH_OVERVIEW_CADENCE_CYCLES: Final = 2
"""Work cycles between periodic firings.

Two rather than one so a firing is separated from the next by a full
generate-and-rank round: an overview drafted from a pool that has not
changed since the last one tells generation nothing new. At this cadence
extended (3 iterations) fires once and ultra (4) at most twice.
"""


def _check_meta_review_cadence(
    stats: SchedulerStats,
) -> SupervisorDecision | None:
    """Step 9: synthesize system-wide feedback periodically (listing 01 L61).

    The listing's "IF enough time has passed" made observable as two
    conditions, both required. A work cycle must have completed since the
    last firing -- the iteration counter, not the decision counter, so a
    ranking wave cannot buy two firings (one before it, one after it
    returns with new matches). And there must be new critique material to
    synthesize: reviews written or tournament participations played since
    the last firing.

    That second condition is also what makes this step terminate. Meta-
    review is not a work task, so it never advances the iteration counter
    and the first condition alone would hold for every remaining loop
    point; a firing that consumed the material it was scheduled for cannot
    immediately re-fire on the same material.

    Placed below every required transition and above convergence: it is
    maintenance, so real work outranks it, but a converging run should
    still hand the terminal overview a current critique rather than the
    one it held two cycles ago.

    Disabled outright when ``meta_review_enabled`` is False (an ablation
    arm running with no meta-review cadence): returning None here suppresses
    both this ordered-check step and the companion form, since
    ``policy._due_companions`` calls this same function. The EVOLVE branch
    still enters the meta_review node, so this removes periodic feedback,
    not the node.
    """
    if not stats.meta_review_enabled:
        return None
    if stats.iterations_since_meta_review < 1:
        return None
    if stats.feedback_since_meta_review < 1:
        return None
    return SupervisorDecision(
        next_task=TaskType.META_REVIEW,
        reason=(
            f"{stats.feedback_since_meta_review} new review(s)/match(es) "
            f"over {stats.iterations_since_meta_review} cycle(s) since the "
            "last system-wide feedback; synthesize it"
        ),
    )


def _check_research_overview_cadence(
    stats: SchedulerStats, budget: Budget
) -> SupervisorDecision | None:
    """Step 10: synthesize an interim overview periodically (L65-69).

    The paper describes the research overview as generated periodically
    and names it as one of the system's two self-improvement channels;
    ours ran once, at termination, with no edge back into generation
    (FIX-6). A firing here returns to the loop point and leaves an
    ``interim_overview`` the next generate cycle reads as context.

    Gated by cost as well as by cadence, which is what separates it from
    meta-review's step directly above: that companion is one ordinary
    call, this is the largest prompt in the system and up to two
    escalation retries behind it, so only a tier declaring at least
    ``RESEARCH_OVERVIEW_MIN_LLM_CALLS`` buys it.

    Terminates for the same reason meta-review's does, by the same
    mechanism: the overview is not a work task and never advances the
    iteration counter itself, so the anchor
    (``orchestrator_bookkeeping._research_overview_anchor``) is reset as
    the decision is taken and the gap reads zero on the very next loop
    point.
    """
    ceiling = budget.max_llm_calls
    if ceiling is None or ceiling < RESEARCH_OVERVIEW_MIN_LLM_CALLS:
        return None
    if stats.iterations_since_research_overview < (
        RESEARCH_OVERVIEW_CADENCE_CYCLES
    ):
        return None
    return SupervisorDecision(
        next_task=TaskType.SYNTHESIZE,
        reason=(
            f"{stats.iterations_since_research_overview} work cycle(s) "
            "since the last research overview; synthesize an interim one "
            "for the next generation cycle"
        ),
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


# Task types the compiled graph's loop-point router can dispatch. Keep in
# sync with the graph's conditional edges.
#
# SYNTHESIZE is the *periodic* research overview (listing 01 L65-69), which
# enters the same node TERMINATE does and returns to the loop point instead
# of ending the run (FIX-6). It is unreachable to the advisory model, whose
# own enum is ``supervisor_decision._PRODUCTIVE_TASKS``, so only the
# deterministic cadence check -- which is tier-gated -- can name it.
#
# META_REVIEW is here because listing 01 L60-63 queues it as its own periodic
# task. It used to be absent, which was not inert: ``_correct_disallowed_task``
# rewrites anything outside this set to GENERATE, so the only way meta-review
# ever ran was as the head of the EVOLVE branch -- and a run that never evolved
# published with an empty ``meta_review``, silently starving generation, the
# ranking judge, proximity, evolution and the final overview of the critique
# feedback each of them reads.
ALLOWED_LOOP_TASKS: frozenset[TaskType] = frozenset(
    {
        TaskType.GENERATE,
        TaskType.REFLECT,
        TaskType.RANK,
        TaskType.EVOLVE,
        TaskType.META_REVIEW,
        TaskType.PROXIMITY,
        TaskType.SYNTHESIZE,
        TaskType.TERMINATE,
    }
)


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

    ``queue_actions`` survive a correction. A correction is a statement about
    the *next task* — the model asked for something the graph cannot dispatch
    or the pool cannot support — and says nothing about the model's reading of
    the durable queue, whose actions name existing task rows by id. Dropping
    them is not a deferral: a failed durable row is revived by nothing
    automatic (``resume_run_tasks`` requeues only ``paused`` rows and the
    expired-lease rescue skips a task whose attempts are spent), and the
    conditions two of these corrections fire on -- fewer than two rankable
    hypotheses, no reviewed hypothesis -- are pool properties that a corrected
    task need not clear. So the Supervisor re-asks on the next loop point,
    ``_needs_queue_adjudication`` re-fires, the same correction fires again,
    and the same revival is discarded again, for as many rounds as the pool
    stays in that state. Carrying them through cannot extend the run: an
    action mutates a queue row's status or priority, never ``next_task``,
    never the iteration counter, and never any allowance the termination
    predicates read.

    Terminating decisions return untouched above, so no stop -- a safety
    block or a spent budget -- ever carries actions through here; those are
    built fresh by ``policy_checks`` and ``supervisor_decision._hard_stop``
    and never pass a ``_correct_*`` helper.

    Args:
        decision: The proposed decision (from :func:`decide_next_task` or an
            LLM Supervisor recommendation).
        stats: The statistics the decision must be consistent with.

    Returns:
        The original decision, or a corrected safe one carrying the proposed
        queue actions, with the reason annotated when it was changed.
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
            return dataclasses.replace(
                corrected, queue_actions=decision.queue_actions
            )
    return decision


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
