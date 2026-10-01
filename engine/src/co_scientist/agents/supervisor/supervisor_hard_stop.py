"""The code-enforced stop no model allocation may bypass.

Split from ``supervisor_decision`` on that module's size cap. Kept
together as one subject: the ordered, code-only termination predicates
(safety, the budget family) and the two deferrals that let owed
tournament coverage or an owed review pass buy one more cycle past an
otherwise-exhausted budget. ``supervisor_decision`` re-exports
:func:`_hard_stop`, so its own callers and the tests that drive it
directly are unchanged.
"""

from __future__ import annotations

from co_scientist.scheduling import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    TerminationReason,
)

# Stops no amount of owed tournament coverage or owed review may defer. The
# content is unsafe, and more work is wrong regardless of either deferral.
# The budget family (including MAX_IDEAS/MAX_MATCHES_PER_IDEA) defers
# instead, because a hypothesis stranded without any tournament result or
# any peer review is a worse outcome than a bounded overshoot of a ceiling
# that exists to catch runaways. There is no CANCELLED entry: cancellation
# is enforced by the durable executor never dispatching another node, not
# by a decision this policy makes (see ``scheduling.TerminationReason``'s
# docstring).
_IMMEDIATE_STOP_REASONS = frozenset({TerminationReason.SAFETY})


def _owed_coverage_is_affordable(stats: SchedulerStats) -> bool:
    """Return whether owed tournament coverage may still defer a stop.

    Read from the allowance state on ``stats`` rather than inferred from the
    scheduler's baseline task. The baseline is only a proxy: on the
    queue-adjudication path the model may be consulted and return a task
    other than RANK, which charges nothing, so a baseline-derived deferral
    was not bounded by anything. The allowance itself is.

    Measured on ``owed_coverage_rounds``, the same quantity
    ``policy._check_owed_coverage`` triggers on. This gate runs *before* the
    scheduler's forced transitions, so a narrower test here stops the run
    before the settlement round it just asked for -- the deferral has to see
    everything the check does or the check never reaches a run.
    """
    allowance = stats.settlement_allowance
    return stats.owed_coverage_rounds > 0 and (
        allowance is None or allowance > 0
    )


def _owed_review_is_affordable(
    stats: SchedulerStats, termination_reason: TerminationReason
) -> bool:
    """Return whether an owed review pass may still defer a stop.

    Mirrors ``_owed_coverage_is_affordable`` immediately above, for the
    same reason: this gate runs *before* the scheduler's forced
    transitions, so a narrower test here would stop the run before the
    review pass ``policy_checks._check_owed_review`` just asked for -- the
    deferral has to see everything that check does or the check never
    reaches a run.

    Unlike owed coverage there is no round-by-round settlement allowance to
    read: the override is spent the moment it fires, marked on issue
    rather than on success (``agents.reflection.owed_review``), so
    ``stats.owed_review_count`` already reads zero once every hypothesis
    that could ever owe one has either been reviewed or had its one
    attempt marked spent. Affordable exactly when it is still positive --
    except against ``TerminationReason.BUDGET``, which this deferral must
    never buy against: the LLM-call ceiling is enforced a second time
    *inside* the forced task by the provider-request seam
    (``llm.admission.call_budget.record_provider_request``), at the same
    boundary with zero headroom (see ``policy_checks._check_owed_review``'s
    docstring for the full argument), so deferring past it here would only let
    the forced task crash on its first provider call instead of stopping
    cleanly.
    """
    if termination_reason is TerminationReason.BUDGET:
        return False
    return stats.owed_review_count > 0


def _budget_exceeded(limit: float | None, value: float) -> bool:
    """Return whether an optional budget ceiling has been reached or passed."""
    return limit is not None and value >= limit


def _max_ideas_exceeded(stats: SchedulerStats, budget: Budget) -> bool:
    """Return whether the idea-pool ceiling is hit with no review owed.

    Mirrors ``policy_checks._max_ideas_check``'s gate: this runs ahead of
    the review-backlog step, so a bare pool-size ceiling would otherwise
    strand the freshest, still-unreviewed ideas.
    """
    limit = budget.max_ideas
    return (
        limit is not None
        and stats.unreviewed_count == 0
        and stats.pool_size >= limit
    )


def _max_matches_per_idea_exceeded(
    stats: SchedulerStats, budget: Budget
) -> bool:
    """Return whether average tournament coverage hit its ceiling.

    Mirrors ``policy_checks._max_matches_per_idea_check``.
    """
    limit = budget.max_matches_per_idea
    return (
        limit is not None
        and stats.rankable_count >= 2
        and stats.match_coverage >= limit
    )


# Ordered (triggered, reason, message) checks for _hard_stop_reason: the
# first true entry wins, matching the original if/elif precedence exactly.
def _hard_stop_checks(
    stats: SchedulerStats, budget: Budget
) -> tuple[tuple[bool, TerminationReason, str], ...]:
    """Build the ordered hard-stop predicates for these stats/budget."""
    return (
        (
            stats.safety_blocked,
            TerminationReason.SAFETY,
            "safety block halted the run",
        ),
        (
            _budget_exceeded(budget.max_llm_calls, stats.llm_calls),
            TerminationReason.BUDGET,
            "LLM-call budget exhausted",
        ),
        (
            _budget_exceeded(budget.max_tasks, stats.tasks_run),
            TerminationReason.MAX_TASKS,
            "task budget exhausted",
        ),
        (
            _budget_exceeded(budget.max_wall_clock_s, stats.elapsed_s),
            TerminationReason.WALL_CLOCK,
            "wall-clock budget exhausted",
        ),
        (
            _max_ideas_exceeded(stats, budget),
            TerminationReason.MAX_IDEAS,
            "idea-pool budget exhausted",
        ),
        (
            _max_matches_per_idea_exceeded(stats, budget),
            TerminationReason.MAX_MATCHES_PER_IDEA,
            "match budget exhausted",
        ),
    )


def _hard_stop_reason(
    stats: SchedulerStats, budget: Budget
) -> tuple[TerminationReason, str] | None:
    """Return the code-enforced termination reason, if any, for these stats."""
    for triggered, reason, message in _hard_stop_checks(stats, budget):
        if triggered:
            return reason, message
    return None


def _hard_stop(
    stats: SchedulerStats,
    budget: Budget,
    baseline: SupervisorDecision,
) -> SupervisorDecision | None:
    """Return a code-enforced stop that no model allocation may bypass.

    Args:
        stats: Live statistics derived from workflow state, including the
            settlement-allowance state that decides whether a budget stop
            may be deferred for owed tournament coverage.
        budget: The run's hard compute limits.
        baseline: The disclosed scheduler's decision for these same
            stats/budget, reused for the satisfied-completion/convergence
            fall-through rather than recomputed.
    """
    reason = _hard_stop_reason(stats, budget)
    if reason is None:
        # Satisfied completion and convergence are evaluated by the disclosed
        # scheduler predicates after required review/ranking/proximity work.
        return baseline if baseline.terminate else None
    termination_reason, message = reason
    if (
        _owed_coverage_is_affordable(stats)
        or _owed_review_is_affordable(stats, termination_reason)
    ) and termination_reason not in _IMMEDIATE_STOP_REASONS:
        # Defer to the scheduler's owed-coverage round or owed-review pass.
        # Owed coverage is held to the settlement allowance the scheduler
        # spends, charged per round and never refilled inside an episode;
        # owed review is held to its own permanent per-hypothesis marker
        # (``agents.reflection.owed_review``), spent the moment the pass
        # fires rather than refilled on failure. Neither can postpone the
        # stop forever.
        return None
    return SupervisorDecision(
        next_task=TaskType.TERMINATE,
        reason=message,
        terminate=True,
        termination_reason=termination_reason,
    )
