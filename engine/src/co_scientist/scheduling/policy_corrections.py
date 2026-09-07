"""Validation of a (possibly LLM-recommended) Supervisor decision.

The code -- not the model -- validates. :func:`validate_decision` runs each
``_correct_*`` precondition over a proposed decision and downgrades it to a
safe alternative rather than executing something the graph cannot dispatch or
the pool cannot support.
"""

from __future__ import annotations

import dataclasses

from co_scientist.scheduling.models import (
    SchedulerStats,
    SupervisorDecision,
    TaskType,
)

# Task types the compiled graph's loop-point router can dispatch. SYNTHESIZE
# is the TERMINATE target. Keep in sync with the graph's conditional edges.
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
