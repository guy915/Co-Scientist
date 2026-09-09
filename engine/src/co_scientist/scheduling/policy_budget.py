"""The budget-adjacent checks: hard ceilings and the owed-review override.

Split from ``policy_checks`` on that module's size cap, and split
together because they are one subject: the ordered hard-ceiling
predicates (``_budget_termination``) and the check immediately above them
in ``policy._ordered_checks`` that can override one of those ceilings for
a single bounded pass (``_check_owed_review``). ``policy_checks``
re-exports every name here, so the policy's own imports and every
existing caller (including the docstring cross-references elsewhere in
this codebase that name ``policy_checks._llm_call_budget_check`` and
``policy_checks._max_ideas_check``) are unchanged.
"""

from __future__ import annotations

from co_scientist.scheduling.models import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    TerminationReason,
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
    (``llm_call_budget.record_provider_request``), at the identical
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
