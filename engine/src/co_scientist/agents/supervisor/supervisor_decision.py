"""Model-directed Supervisor allocation at each orchestration loop point."""

from __future__ import annotations

import dataclasses
import json
import logging
from typing import Any

from co_scientist.constants import MEDIUM_TEMPERATURE
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm_json,
)
from co_scientist.scheduling import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    TerminationReason,
    decide_next_task,
    required_transition,
    validate_decision,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

_PRODUCTIVE_TASKS = (
    TaskType.GENERATE,
    TaskType.REFLECT,
    TaskType.RANK,
    TaskType.EVOLVE,
    TaskType.PROXIMITY,
)

# Work tasks grow the hypothesis pool and advance the iteration counter, unlike
# maintenance tasks (reflect/rank/proximity). Shared so the orchestrator's
# iteration bookkeeping and the post-budget growth guard here agree on the set.
WORK_TASKS = frozenset({TaskType.GENERATE, TaskType.EVOLVE})

# Stops no amount of owed tournament coverage may defer. The content is
# unsafe, and more work is wrong regardless of coverage. The budget family
# (including MAX_IDEAS/MAX_MATCHES_PER_IDEA) defers instead, because a
# hypothesis stranded without any tournament result is a worse outcome than
# a bounded overshoot of a ceiling that exists to catch runaways. There is no
# CANCELLED entry: cancellation is enforced by the durable executor never
# dispatching another node, not by a decision this policy makes (see
# ``scheduling.TerminationReason``'s docstring).
_IMMEDIATE_STOP_REASONS = frozenset({TerminationReason.SAFETY})

# Every constraint below is executable, not documentation. Production's
# provider enforces none of it -- DeepSeek only accepts json_object, where
# this schema reaches the model as prompt text and nothing server-side
# checks the reply -- but ``call_llm_json`` validates each parsed response
# against this same schema in-process before returning it
# (``llm_json.validate_json_schema``). So a bound declared here is enforced
# here: an out-of-range or non-integer priority, at either level, never
# reaches ``SupervisorDecision``. It fails validation, the retry carries
# the error back to the model, and a model that keeps violating loses the
# whole allocation to the deterministic scheduler under
# "reconstructed-fallback" provenance. Do not widen or drop a bound to
# quiet a retry: that turns a recorded contract violation into a silently
# accepted value. (``minimum``/``maximum`` constrain numbers only, so the
# ``["integer", "null"]`` union does not defeat them; null is the declared
# "leave this task's priority alone" value.) The app re-bounds once more
# where these land in its queue -- a receiver defending an input it does
# not control, not a duplicate of this.
#
# The one constraint this does *not* enforce is the top-level ``required``
# list. For json_object-only providers -- production -- the
# ``_backfill_required_fields`` shim fills missing required fields with
# type-neutral defaults before validating, so a reply omitting
# ``next_task`` is silently completed with the enum's first value and
# recorded as a model decision the model never made. The nested
# ``required`` inside ``queue_actions`` items is unaffected: the shim
# returns at the array and never descends into its items. Both properties
# are pinned by tests/test_supervisor_decision_schema.py.
_DECISION_SCHEMA: dict[str, Any] = {
    "name": "supervisor_allocation",
    "schema": {
        "type": "object",
        "properties": {
            "next_task": {
                "type": "string",
                "enum": [task.value for task in _PRODUCTIVE_TASKS],
            },
            "reason": {"type": "string", "minLength": 1},
            "priority": {"type": "integer", "minimum": 0, "maximum": 100},
            "queue_actions": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["reprioritize", "cancel", "retry"],
                        },
                        "task_id": {"type": "string", "minLength": 1},
                        "priority": {
                            "type": ["integer", "null"],
                            "minimum": 0,
                            "maximum": 100,
                        },
                        "reason": {"type": "string", "minLength": 1},
                    },
                    "required": ["action", "task_id", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["next_task", "reason"],
        "additionalProperties": False,
    },
}


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
        and termination_reason not in _IMMEDIATE_STOP_REASONS
    ):
        # Defer to the scheduler's owed-coverage round. Held to the same
        # settlement allowance the scheduler spends, which is charged per
        # settlement round and never refilled inside an episode, so the
        # deferral cannot postpone the stop forever.
        return None
    return SupervisorDecision(
        next_task=TaskType.TERMINATE,
        reason=message,
        terminate=True,
        termination_reason=termination_reason,
    )


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


def _planning_prompt(
    state: WorkflowState, stats: SchedulerStats, budget: Budget
) -> str:
    """Build the Supervisor's live allocation prompt from shared memory."""
    context = {
        "research_goal": state["research_goal"],
        "research_plan": state.get("supervisor_guidance") or {},
        "statistics": stats.to_dict(),
        "budget": budget.to_dict(),
        "recent_tasks": state.get("task_history", [])[-12:],
        "meta_review": state.get("meta_review") or {},
        "pending_steering": state.get("pending_steering") or False,
        "held_for_review": len(state.get("held_for_review", [])),
        "durable_task_queue": state.get("durable_task_queue") or [],
    }
    return (
        "You are the adaptive Supervisor for a scientific co-research system. "
        "Allocate the single most valuable next specialist task from generate, "
        "reflect, rank, evolve, or proximity. Use the live state rather than a "
        "fixed phase order. Prioritize unresolved verification and review work "
        "as hypotheses mature, incorporate scientist steering immediately, and "
        "balance exploration against improvement. Explain the observable basis "
        "for the allocation without revealing hidden chain-of-thought. Use "
        "queue_actions only when a listed queued/failed task should be "
        "reprioritized, cancelled as superseded, or retried because state has "
        "materially changed. Never target an unlisted task.\n\n"
        "Live shared memory:\n"
        f"{json.dumps(context, sort_keys=True, default=str)}"
    )


def _repeats_without_iteration_progress(
    state: WorkflowState,
    stats: SchedulerStats,
    proposed: SupervisorDecision,
    baseline: SupervisorDecision,
) -> bool:
    """Detect a model allocation that already ran in the current cycle."""
    if proposed.next_task is baseline.next_task:
        return False
    return any(
        str(record.get("task_type")) == proposed.next_task.value
        and int(record.get("iteration", -1)) == stats.iteration
        for record in state.get("task_history", [])
    )


def _needs_queue_adjudication(state: WorkflowState) -> bool:
    """Return whether a failed durable task needs a model queue action.

    A failed durable task is not revived by anything automatic: the retry
    budget is spent, resume only requeues *paused* rows, and the Supervisor's
    ``queue_actions`` are the sole route back. Skipping the planning call
    while one is pending would strand it for the rest of the run, so a
    failed row makes even a forced transition worth the round-trip.
    """
    return any(
        str(entry.get("status")) == "failed"
        for entry in state.get("durable_task_queue") or ()
    )


async def choose_supervisor_task(
    state: WorkflowState,
    stats: SchedulerStats,
    budget: Budget,
) -> tuple[SupervisorDecision, str, int]:
    """Choose the next productive task, consulting the model only if needed.

    Hard safety and compute limits are enforced before the model call. A
    malformed or unavailable planning call falls back to the
    existing deterministic policy and records that provenance explicitly.

    Most loop points do not present a choice. The disclosed scheduler's
    steps 1-10 are required transitions -- review an unreviewed backlog,
    grow a pool too small to rank, refresh stale proximity, stop on a spent
    budget -- and the guards below would overrule a model that disagreed
    with them anyway. Spending an uncached planning round-trip to be told
    what the code already decided costs the run real wall-clock time on its
    serial spine, so a forced transition returns immediately and the model
    is consulted only for the open generation-vs-evolution judgement.

    Args:
        state: Current shared workflow state.
        stats: Live statistics derived from that state.
        budget: The run's hard compute limits.

    Returns:
        The validated decision, its provenance label, and the real LLM
        calls this allocation spent -- 1 exactly when the planner was
        actually consulted (whether it succeeded or fell back on
        exception), 0 for a hard-stop or required transition, both decided
        entirely in code (finding L3 -- orchestrator allocation previously
        reported no llm_calls at all).
    """
    # The disclosed scheduler's decision for these stats/budget. Computed once
    # and reused for the hard-stop fall-through, the non-progress fallback, the
    # post-budget growth guard, and the exception fallback -- the policy is
    # pure and stats/budget do not change across those uses.
    forced = required_transition(stats, budget)
    baseline = forced if forced is not None else decide_next_task(stats, budget)

    stop = _hard_stop(stats, budget, baseline)
    if stop is not None:
        return stop, "hard-invariant", 0

    if forced is not None and not _needs_queue_adjudication(state):
        return validate_decision(forced, stats), "required-transition", 0

    try:
        validated = await _call_supervisor_planner(state, stats, budget)
        decision, provenance = _resolve_planner_decision(
            state, stats, budget, baseline, validated
        )
        return decision, provenance, 1
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception as exc:
        logger.warning("Supervisor allocation failed; using fallback: %s", exc)
        fallback = validate_decision(baseline, stats)
        return fallback, "reconstructed-fallback", 1


async def _call_supervisor_planner(
    state: WorkflowState, stats: SchedulerStats, budget: Budget
) -> SupervisorDecision:
    """Calls the allocation model and validates its proposed allocation.

    Runs on the worker model with thinking on. Note where this call sits:
    the required transitions are already settled in code, so what reaches
    the model is the open generation-vs-evolution judgement, and the whole
    cohort waits on the answer -- this is the run's serial spine, where
    latency is added wall-clock time rather than time overlapped with other
    work. Every answer stays bounded by ``validate_decision`` and the guards
    around it.
    """
    response = await call_llm_json(
        prompt=_planning_prompt(state, stats, budget),
        spec=CompletionSpec(
            model_name=state["model_name"],
            temperature=MEDIUM_TEMPERATURE,
            json_schema=_DECISION_SCHEMA,
        ),
        options=LLMCallOptions(
            use_cache=False,
            run_id=state.get("run_id"),
            prompt_name="supervisor_allocation",
            prompt_metadata={"iteration": stats.iteration},
        ),
    )
    # The schema validation inside call_llm_json has already bounded both
    # priorities and typed every queue action (see _DECISION_SCHEMA), so
    # the clamp here is belt-and-braces with two live effects: the 50
    # default for a priority the schema leaves optional, and int()
    # normalizing the integral float that JSON Schema's "integer" admits
    # (55.0), so a real int leaves the engine. Queue actions pass through
    # as parsed for the same reason -- they are already in range.
    proposed = SupervisorDecision(
        next_task=TaskType(str(response["next_task"])),
        reason=str(response["reason"]),
        priority=max(0, min(100, int(response.get("priority", 50)))),
        queue_actions=tuple(response.get("queue_actions") or ()),
    )
    return validate_decision(proposed, stats)


def _overruled(
    baseline: SupervisorDecision, validated: SupervisorDecision
) -> SupervisorDecision:
    """Return the baseline, still carrying the proposal's queue actions.

    Both guards below overrule the model's *next task*. Neither says anything
    about its reading of the durable queue, whose actions name existing task
    rows by id -- so the queue actions survive, exactly as they now do when
    ``validate_decision`` corrects a task (see ``policy_corrections``).

    Dropping them was not a one-round deferral. Measured over the real loop:
    with the iteration budget spent and a review backlog keeping the baseline
    non-terminating, the post-budget guard fired on 60 of 60 planning calls,
    every one of them carrying a revival for a failed durable row, and the
    revival landed in 0 of 20 runs -- ``stats.iteration`` never decreases, so
    that guard's condition latches for the rest of the run and the row stays
    failed through termination. Nothing automatic revives it: resume requeues
    only *paused* rows and the expired-lease rescue skips a task whose
    attempts are spent. The non-progress guard clears once a work cycle
    advances the iteration, but not for free -- it delayed the same revival by
    up to four rounds and doubled the planning calls spent re-asking for it.

    Which of the two happens was also arbitrary: with identical stats and the
    identical action, delivery turned on whether the model's chosen next task
    happened to be a work task (18 delivered, 11 discarded over the same 29
    calls).

    Terminating decisions cannot reach here -- ``choose_supervisor_task``
    returns a stop before calling this, and ``_hard_stop`` returns the
    baseline itself whenever it terminates -- so no stop ever carries queue
    actions through. That short-circuit is load-bearing for the blanket
    carry-through, not incidental.
    """
    if not validated.queue_actions:
        return baseline
    return dataclasses.replace(baseline, queue_actions=validated.queue_actions)


def _resolve_planner_decision(
    state: WorkflowState,
    stats: SchedulerStats,
    budget: Budget,
    baseline: SupervisorDecision,
    validated: SupervisorDecision,
) -> tuple[SupervisorDecision, str]:
    """Applies the non-progress and post-budget-growth guards to a proposal."""
    if _repeats_without_iteration_progress(state, stats, validated, baseline):
        # A freeform Supervisor may spend one maintenance pass beyond the
        # baseline, but repeating the same pass without a work-cycle
        # advance is a non-progress loop. Fall back to the disclosed
        # scheduler and record that the code-enforced invariant fired.
        return _overruled(baseline, validated), "hard-invariant"
    if (
        not stats.pending_steering
        and stats.iteration >= budget.max_iterations
        and validated.next_task in WORK_TASKS
    ):
        # Once the exploration budget is spent, the model may select the
        # required review/ranking/proximity cleanup but cannot grow the
        # pool again. The deterministic policy owns that terminal drain.
        return _overruled(baseline, validated), "hard-invariant"
    return validated, "model"
