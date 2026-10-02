"""Meta-review is an independently dispatchable periodic task (FIX-2).

Listing 01 (``01-supervisor.md`` L60-63) queues ``GenerateSystemFeedback``
from ``DecideNextSteps`` as its own periodic task, and listing 07 defines
it as a standalone function. Ours was reachable only as EVOLVE's prefix
node: ``META_REVIEW`` was missing from ``ALLOWED_LOOP_TASKS``, so
``_correct_disallowed_task`` rewrote any such recommendation to
``GENERATE``. A run that never evolved therefore shipped with an empty
``meta_review`` and five consumers -- generation, the ranking judge,
proximity, evolution and the final overview -- lost their critique
feedback with no error anywhere.

These are control-flow-shape assertions: that the task is dispatchable,
that the cadence fires on new critique material and stops firing without
it, and that the graph can return from meta-review to the loop point
rather than only falling through to evolve.
"""

from __future__ import annotations

from co_scientist.scheduling import (
    ALLOWED_LOOP_TASKS,
    Budget,
    SchedulerStats,
    TaskType,
)
from co_scientist.scheduling.policy import decide_next_task, validate_decision
from co_scientist.scheduling.policy_cadence import _check_meta_review_cadence
from co_scientist.task_runtime import next_task_type
from co_scientist.workflow_topology import (
    TASK_ROUTES,
    route_after_meta_review,
)
from tests._state import make_state

_BUDGET = Budget(max_iterations=4)


def _settled_stats(**overrides: object) -> SchedulerStats:
    """Stats for a run with nothing more urgent than periodic feedback.

    Everything the checks above the cadence step read is satisfied: no
    safety stop, no steering, no owed coverage, no failed task, no review
    backlog, a rankable pool, coverage met, and proximity fresh.
    """
    base: dict[str, object] = {
        "pool_size": 6,
        "reviewed_count": 6,
        "unreviewed_count": 0,
        "rankable_count": 6,
        "total_matches": 12,
        "match_coverage": 2.0,
        "iteration": 1,
        "iterations_since_meta_review": 1,
        "feedback_since_meta_review": 6,
    }
    base.update(overrides)
    return SchedulerStats(**base)  # type: ignore[arg-type]


def test_meta_review_is_a_dispatchable_loop_task() -> None:
    """The scheduler may name meta-review; nothing rewrites it away."""
    assert TaskType.META_REVIEW in ALLOWED_LOOP_TASKS
    decision = validate_decision(
        decide_next_task(_settled_stats(), _BUDGET), _settled_stats()
    )
    assert decision.next_task is TaskType.META_REVIEW


def test_cadence_fires_once_new_critique_material_exists() -> None:
    """The listing's "enough time" made observable: a cycle plus new input."""
    assert _check_meta_review_cadence(_settled_stats()) is not None


def test_cadence_holds_without_a_completed_work_cycle() -> None:
    """The clock is the iteration counter, not the decision counter.

    Counting orchestrator decisions would fire before a ranking wave and
    again the moment it returned with new matches -- twice per cycle.
    """
    stats = _settled_stats(iterations_since_meta_review=0)
    assert _check_meta_review_cadence(stats) is None


def test_cadence_holds_without_new_reviews_or_matches() -> None:
    """A second firing with nothing new to synthesize is a wasted call.

    This is also what bounds the step: meta-review is not a work task, so
    it never advances the iteration counter and could otherwise be chosen
    on every remaining loop point.
    """
    stats = _settled_stats(feedback_since_meta_review=0)
    assert _check_meta_review_cadence(stats) is None


def test_cadence_never_outranks_a_review_backlog() -> None:
    """Periodic feedback is below every required transition, as listed."""
    stats = _settled_stats(unreviewed_count=3)
    assert decide_next_task(stats, _BUDGET).next_task is TaskType.REFLECT


def test_a_run_that_never_evolves_still_reaches_meta_review() -> None:
    """The drift itself: critique feedback no longer depends on evolving.

    The route table is what made it dependent -- ``meta_review`` was
    reachable only as the node EVOLVE enters at.
    """
    assert TASK_ROUTES[TaskType.META_REVIEW.value] == "meta_review"
    assert TASK_ROUTES[TaskType.EVOLVE.value] == "meta_review"


def test_meta_review_returns_to_the_loop_point_when_standalone() -> None:
    """Both paths share one resolver, so the shape cannot drift apart."""
    state = make_state(next_task=TaskType.META_REVIEW.value)
    assert route_after_meta_review(state) == "orchestrator"
    assert next_task_type("meta_review", state) == "orchestrator"


def test_meta_review_still_prefixes_evolve() -> None:
    """The existing critique-feeds-evolve edge is unchanged."""
    state = make_state(next_task=TaskType.EVOLVE.value)
    assert route_after_meta_review(state) == "evolve"
    assert next_task_type("meta_review", state) == "evolve"
