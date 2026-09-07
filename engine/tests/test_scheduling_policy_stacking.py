"""One DecideNextSteps pass may stack a follow-up task (FIX-3).

Listing 01's ``DecideNextSteps`` is four **independent** ``IF``s -- rank,
evolve, meta-review, report -- each queueing its own task. Ours collapsed
them into a single-winner precedence chain: one loop point produced
exactly one task, so whichever branch won suppressed the rest, which is
why S12/S13/S14/S15 each read as "conditional where the listing is
unconditional".

Only the cheap companion is stacked here: meta-review, whose whole cost
is one LLM call. A stacked ranking wave would be +4 to +12 judged
multi-turn debates per orchestrator cycle, and is deliberately not done.

The assertions are about control-flow shape: that a pass produces two
tasks, that the primary's own identity survives (the settlement and
iteration accounting all key on it), and that the terminal decision is
never wrapped.
"""

from __future__ import annotations

from co_scientist.generator.graph import (
    _route_after_meta_review,
    _route_next_task,
)
from co_scientist.scheduling import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    stacked_task_values,
)
from co_scientist.scheduling.policy import decide_next_task, stack_companions
from co_scientist.task_runtime import plan_portfolio
from tests._state import make_state

_BUDGET = Budget(max_iterations=4)


def _due_stats(**overrides: object) -> SchedulerStats:
    """Stats with meta-review due and some other task already winning."""
    base: dict[str, object] = {
        "pool_size": 6,
        "reviewed_count": 6,
        "unreviewed_count": 2,
        "rankable_count": 6,
        "total_matches": 12,
        "match_coverage": 2.0,
        "iteration": 1,
        "iterations_since_meta_review": 1,
        "feedback_since_meta_review": 6,
    }
    base.update(overrides)
    return SchedulerStats(**base)  # type: ignore[arg-type]


def test_one_pass_queues_the_primary_and_its_companion() -> None:
    """The review backlog wins the chain; meta-review is queued anyway."""
    stats = _due_stats()
    decision = stack_companions(decide_next_task(stats, _BUDGET), stats)
    assert decision.next_task is TaskType.REFLECT
    assert stacked_task_values(decision.queue_actions) == (
        TaskType.META_REVIEW.value,
    )


def test_the_primary_keeps_its_own_identity() -> None:
    """Stacking is additive: nothing that reads ``next_task`` shifts.

    The settlement allowance (``_is_settlement_rank``), the iteration
    counter (``_advance_iteration``) and the yield attribution all key on
    the decision's own task, so a wrap that renamed it would silently
    unbound the settlement episode.
    """
    stats = _due_stats(unreviewed_count=0, owed_coverage_rounds=3)
    decision = stack_companions(decide_next_task(stats, _BUDGET), stats)
    assert decision.next_task is TaskType.RANK
    assert stacked_task_values(decision.queue_actions)


def test_a_terminating_decision_is_never_wrapped() -> None:
    """A stop carries no companion; ``terminate`` gates too much to touch.

    The spent-budget stop is checked above the cadence step, so the pass
    really does reach ``stack_companions`` with the cadence due.
    """
    stats = _due_stats(unreviewed_count=0, llm_calls=99)
    spent = Budget(max_iterations=4, max_llm_calls=1)
    decision = stack_companions(decide_next_task(stats, spent), stats)
    assert decision.terminate
    assert not stacked_task_values(decision.queue_actions)


def test_evolve_is_not_stacked_because_it_already_runs_meta_review() -> None:
    """EVOLVE enters at the meta_review node; stacking would double it."""
    evolve = SupervisorDecision(
        next_task=TaskType.EVOLVE, reason="evolution out-yields generation"
    )
    stacked = stack_companions(evolve, _due_stats())
    assert not stacked_task_values(stacked.queue_actions)


def test_nothing_is_stacked_when_the_cadence_is_not_due() -> None:
    """The companion rides the same predicate as the standalone step."""
    stats = _due_stats(feedback_since_meta_review=0)
    decision = stack_companions(decide_next_task(stats, _BUDGET), stats)
    assert not stacked_task_values(decision.queue_actions)


def test_a_stacked_pass_runs_the_companion_before_the_primary() -> None:
    """Both routers put the stacked companion first, then the primary.

    Serial, not parallel: the durable path's checkpoint chain has exactly
    one writer per commit, so two rows anchored to the same predecessor
    would fork it. Stacking is therefore an ordering, and the companion's
    own successor is the primary the pass already decided.
    """
    state = make_state(next_task=TaskType.REFLECT.value)
    state["supervisor_queue_actions"] = [
        {
            "action": "enqueue",
            "task_type": TaskType.META_REVIEW.value,
            "reason": "periodic system feedback",
        }
    ]
    assert _route_next_task(state) == "meta_review"
    assert _route_after_meta_review(state) == "review"
    assert plan_portfolio("meta_review", state) == ["meta_review", "review"]


def test_an_unstacked_pass_routes_straight_to_the_primary() -> None:
    """Without a companion the loop point is exactly as it was."""
    state = make_state(next_task=TaskType.REFLECT.value)
    assert _route_next_task(state) == "review"
