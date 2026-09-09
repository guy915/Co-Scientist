"""Owed-review override marking: once per hypothesis, never re-armed.

Covers the orchestrator-side half of HITL-MANUAL-HYP-001's closed window.
``_owed_review_override_marks`` marks every hypothesis currently owed the
override the moment ``_check_owed_review`` fires this cycle -- before the
forced review's own outcome (or whether it even runs) is known -- and only
when that check is actually asking for one: an ordinary review-backlog
REFLECT on a healthy run must not spend it.

Every scenario here exhausts the budget via ``max_tasks``, never
``max_llm_calls``: the LLM-call ceiling is also enforced *inside* a task by
the provider-request seam at the identical boundary with zero headroom, so
``_check_owed_review`` refuses to override that specific reason (see its
docstring in ``scheduling.policy_budget``) -- a forced REFLECT against an
exhausted LLM-call budget would crash on its first provider call instead of
running. ``test_scheduling_policy_owed_review.py`` pins that refusal
directly; the tests below exercise the reasons the override still covers.

The sequential tests at the bottom are the actual termination proof: a
run whose forced review succeeds terminates cleanly on the next cycle,
and so does one whose forced review fails -- the override never re-fires
for the same hypothesis either way.
"""

import asyncio

from co_scientist.agents.reflection.owed_review import (
    owed_review_count as _owed_review_count,
)
from co_scientist.agents.reflection.owed_review import owed_review_issued
from co_scientist.agents.supervisor.orchestrator import orchestrator_node
from co_scientist.agents.supervisor.orchestrator_bookkeeping import (
    _is_owed_review_override,
    _owed_review_override_marks,
)
from co_scientist.models import Hypothesis
from co_scientist.scheduling import (
    Budget,
    SchedulerStats,
    TaskType,
    TerminationReason,
    decide_next_task,
)
from tests._state import make_hypothesis, make_review, make_state

_EXHAUSTED_BUDGET = Budget(max_iterations=5, max_tasks=3)
_HEALTHY_BUDGET = Budget(max_iterations=5, max_tasks=1000)


def _owed_stats(**overrides: object) -> SchedulerStats:
    base: dict[str, object] = {
        "pool_size": 2,
        "reviewed_count": 1,
        "unreviewed_count": 1,
        "rankable_count": 1,
        "owed_review_count": 1,
        "tasks_run": 3,
    }
    base.update(overrides)
    return SchedulerStats(**base)  # type: ignore[arg-type]


def test_the_override_marks_the_hypothesis_owed_this_cycle() -> None:
    hypothesis = make_hypothesis()
    stats = _owed_stats()

    marked = _owed_review_override_marks(stats, _EXHAUSTED_BUDGET, [hypothesis])

    assert marked == [hypothesis]
    assert owed_review_issued(hypothesis)


def test_an_ordinary_backlog_reflect_on_a_healthy_run_marks_nothing() -> None:
    # _check_owed_review is gated on the budget already being exhausted, so
    # a run with room to spare must not spend the override -- it would
    # exhaust the run-wide cap on cycles that never needed it.
    hypothesis = make_hypothesis()
    stats = _owed_stats(owed_review_count=0)

    marked = _owed_review_override_marks(stats, _HEALTHY_BUDGET, [hypothesis])

    assert marked == []
    assert not owed_review_issued(hypothesis)


def test_marking_does_not_depend_on_which_task_actually_executes() -> None:
    # A consulted planner on the queue-adjudication path may return a task
    # other than REFLECT even though this check supplied the forced
    # baseline (supervisor_decision._needs_queue_adjudication). Marking
    # fires on the check itself, not on the executed decision, so that
    # diversion cannot leave the override neither spent nor bounded.
    hypothesis = make_hypothesis()
    stats = _owed_stats()

    assert _is_owed_review_override(stats, _EXHAUSTED_BUDGET)
    marked = _owed_review_override_marks(stats, _EXHAUSTED_BUDGET, [hypothesis])

    assert marked == [hypothesis]
    assert owed_review_issued(hypothesis)


def test_orchestrator_forces_review_before_budget_can_terminate() -> None:
    """A budget-exhausting admission still gets scheduled for review."""
    hypothesis = make_hypothesis("newcomer")
    state = make_state(
        hypotheses=[hypothesis],
        budget={"max_iterations": 5, "max_tasks": 1},
        task_history=[{"task_type": "generate", "iteration": 0}],
        current_iteration=0,
    )

    delta = asyncio.run(orchestrator_node(state))

    assert delta["next_task"] == TaskType.REFLECT.value
    assert not delta.get("termination_reason")
    marked = delta["hypotheses"]
    assert marked == [hypothesis]
    assert owed_review_issued(hypothesis)


def test_orchestrator_does_not_touch_hypotheses_on_an_unrelated_decision() -> (
    None
):
    """No spurious ``hypotheses`` delta when the override never fires."""
    hyps = [make_hypothesis(f"h{i}", elo_rating=1200) for i in range(4)]
    state = make_state(hypotheses=hyps, current_iteration=0)

    delta = asyncio.run(orchestrator_node(state))

    assert delta.get("hypotheses") in (None, [])


def test_a_failed_review_does_not_re_arm_the_override_next_cycle() -> None:
    """The whole point: budget terminates even if the review never lands."""
    hypothesis = make_hypothesis()  # never reviewed
    pool: list[Hypothesis] = [hypothesis]
    stats = SchedulerStats(
        pool_size=1,
        unreviewed_count=1,
        owed_review_count=_owed_review_count(pool),
        tasks_run=3,
    )
    decision = decide_next_task(stats, _EXHAUSTED_BUDGET)
    assert decision.next_task is TaskType.REFLECT

    marked = _owed_review_override_marks(stats, _EXHAUSTED_BUDGET, pool)
    assert marked == pool
    assert owed_review_issued(hypothesis)

    # The forced review ran and failed: still no peer review.
    next_stats = SchedulerStats(
        pool_size=1,
        unreviewed_count=1,
        owed_review_count=_owed_review_count(pool),
        tasks_run=3,
    )
    next_decision = decide_next_task(next_stats, _EXHAUSTED_BUDGET)

    assert next_decision.terminate
    assert next_decision.termination_reason is TerminationReason.MAX_TASKS


def test_a_successful_review_also_terminates_cleanly_next_cycle() -> None:
    hypothesis = make_hypothesis()
    pool: list[Hypothesis] = [hypothesis]
    stats = SchedulerStats(
        pool_size=1,
        unreviewed_count=1,
        owed_review_count=_owed_review_count(pool),
        tasks_run=3,
    )
    decision = decide_next_task(stats, _EXHAUSTED_BUDGET)
    assert decision.next_task is TaskType.REFLECT
    _owed_review_override_marks(stats, _EXHAUSTED_BUDGET, pool)

    # The forced review succeeded this time.
    hypothesis.reviews.append(make_review())

    next_stats = SchedulerStats(
        pool_size=1,
        unreviewed_count=0,
        owed_review_count=_owed_review_count(pool),
        tasks_run=3,
    )
    next_decision = decide_next_task(next_stats, _EXHAUSTED_BUDGET)

    assert next_decision.terminate
    assert next_decision.termination_reason is TerminationReason.MAX_TASKS


def test_the_override_never_fires_against_an_exhausted_llm_call_budget() -> (
    None
):
    """The seam boundary this refusal exists for (see policy_budget)."""
    hypothesis = make_hypothesis()
    exhausted_llm_budget = Budget(max_iterations=5, max_llm_calls=10)
    stats = _owed_stats(tasks_run=0, llm_calls=10)

    decision = decide_next_task(stats, exhausted_llm_budget)

    assert decision.terminate
    assert decision.termination_reason is TerminationReason.BUDGET
    marked = _owed_review_override_marks(
        stats, exhausted_llm_budget, [hypothesis]
    )
    assert marked == []
    assert not owed_review_issued(hypothesis)
