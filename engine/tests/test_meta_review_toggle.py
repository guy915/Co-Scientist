"""The periodic meta-review cadence can be disabled per run (ablation seam).

``enable_meta_review=False`` in a run's opts threads to the workflow state,
into ``SchedulerStats.meta_review_enabled``, and gates
``policy_cadence._check_meta_review_cadence`` -- which is read by both the
ordered-check step and the companion path, so one flag disables both. The
EVOLVE branch still enters the meta_review node, so this removes the
*periodic* system-wide feedback, not the node; these tests assert exactly
that scope. Wired for ``evaluations.ablation_driver``'s ``no_meta_review``
arm.
"""

from __future__ import annotations

from co_scientist.agents.supervisor.orchestrator_stats import _compute_stats
from co_scientist.scheduling.models import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    stacked_task_values,
)
from co_scientist.scheduling.policy import (
    _check_meta_review_cadence,
    decide_next_task,
    stack_companions,
)
from tests._state import make_state

_BUDGET = Budget(max_iterations=4, max_llm_calls=7000)


def _due_stats(**overrides: object) -> SchedulerStats:
    """Stats with the meta-review cadence due (a cycle and material since)."""
    base: dict[str, object] = {
        "pool_size": 6,
        "reviewed_count": 6,
        "unreviewed_count": 0,
        "rankable_count": 6,
        "total_matches": 12,
        "match_coverage": 2.0,
        "owed_coverage_rounds": 3,
        "iteration": 1,
        "iterations_since_meta_review": 1,
        "feedback_since_meta_review": 6,
    }
    base.update(overrides)
    return SchedulerStats(**base)  # type: ignore[arg-type]


def test_cadence_fires_when_enabled_and_due() -> None:
    """The default (enabled) path is unchanged: a due cadence fires."""
    decision = _check_meta_review_cadence(_due_stats())
    assert decision is not None
    assert decision.next_task is TaskType.META_REVIEW


def test_cadence_suppressed_when_disabled_even_though_due() -> None:
    """meta_review_enabled=False returns None despite the cadence being due."""
    assert (
        _check_meta_review_cadence(_due_stats(meta_review_enabled=False))
        is None
    )


def test_disabled_cadence_stacks_no_meta_review_companion() -> None:
    """The companion rides the same gated predicate as the standalone step.

    With the cadence enabled a non-terminating primary carries a
    META_REVIEW companion; disabling it removes that companion, so no
    periodic meta-review is queued from either path.
    """
    enabled = _due_stats(unreviewed_count=0)
    stacked = stack_companions(
        decide_next_task(enabled, _BUDGET), enabled, _BUDGET
    )
    assert TaskType.META_REVIEW.value in stacked_task_values(
        stacked.queue_actions
    )

    disabled = _due_stats(unreviewed_count=0, meta_review_enabled=False)
    stacked_off = stack_companions(
        decide_next_task(disabled, _BUDGET), disabled, _BUDGET
    )
    assert TaskType.META_REVIEW.value not in stacked_task_values(
        stacked_off.queue_actions
    )


def test_evolve_still_enters_meta_review_when_cadence_disabled() -> None:
    """Disabling the cadence is not disabling the node.

    An EVOLVE primary carries no meta-review companion (it enters that node
    itself), and disabling the cadence does not change that -- the node is
    still reached via EVOLVE, which is what keeps the run's critique
    channel to evolution intact.
    """
    evolve = SupervisorDecision(
        next_task=TaskType.EVOLVE, reason="evolution out-yields generation"
    )
    stacked = stack_companions(
        evolve, _due_stats(meta_review_enabled=False), _BUDGET
    )
    assert not stacked_task_values(stacked.queue_actions)


def test_state_flag_threads_into_scheduler_stats() -> None:
    """enable_meta_review in state reaches SchedulerStats.meta_review_enabled.

    Default (absent/True) leaves it on; an explicit False turns it off.
    """
    on = _compute_stats(make_state(), {})
    assert on.meta_review_enabled is True
    off = _compute_stats(make_state(enable_meta_review=False), {})
    assert off.meta_review_enabled is False
