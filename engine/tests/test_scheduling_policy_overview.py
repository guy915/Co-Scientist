"""FIX-6: the research overview is periodic and feeds back into generation.

The paper describes the research overview as generated *periodically* and
names it as one of the system's two self-improvement channels (the other
is meta-review's critique). Ours ran exactly once, at termination, with no
edge back into generation: listing 01 L65-69's ``GenerateFinalResearchOverview``
was mirrored, its periodic sibling was missing, and nothing the overview
concluded could reach the ideas still being drafted.

The routing groundwork is meta-review's (commit ``7a4dbfbc``): a cadence
check, a dispatchable task value, and a split successor edge that returns
to the loop point. This mirrors that shape for ``SYNTHESIZE`` rather than
inventing a second one.

Unlike meta-review's one cheap call, the overview is the largest prompt in
the system and the caller most likely to climb the budget-escalation
ladder, so a firing is budgeted at one call plus up to two escalation
retries and is gated to the tiers that can pay for it: extended (7000
calls) and ultra (14000), never express or standard.

These are control-flow-shape assertions: that the firing is gated by tier
*and* cadence rather than fired every cycle, that it returns to the
orchestrator instead of terminating the run, and that what it writes
reaches generation.
"""

from __future__ import annotations

from co_scientist.agents.meta_review.interim_overview import (
    build_interim_overview,
    format_interim_overview,
)
from co_scientist.scheduling import (
    ALLOWED_LOOP_TASKS,
    Budget,
    SchedulerStats,
    TaskType,
)
from co_scientist.scheduling.policy import decide_next_task, validate_decision
from co_scientist.scheduling.policy_cadence import (
    _check_research_overview_cadence,
)
from co_scientist.task_runtime import next_task_type
from co_scientist.workflow_topology import (
    TASK_ROUTES,
    route_after_research_overview,
)
from tests._state import make_state

# Extended's own ceiling: the cheapest tier that funds a periodic firing.
_EXTENDED = Budget(max_iterations=3, max_llm_calls=7000)
_STANDARD = Budget(max_iterations=3, max_llm_calls=2500)


def _settled_stats(**overrides: object) -> SchedulerStats:
    """Stats for a run with nothing more urgent than periodic synthesis.

    Everything above this step is satisfied, including meta-review's own
    cadence (which outranks it: the overview should read a current
    critique, not the one held two cycles ago).
    """
    base: dict[str, object] = {
        "pool_size": 6,
        "reviewed_count": 6,
        "unreviewed_count": 0,
        "rankable_count": 6,
        "total_matches": 12,
        "match_coverage": 2.0,
        "iteration": 2,
        "iterations_since_meta_review": 0,
        "feedback_since_meta_review": 0,
        "iterations_since_research_overview": 2,
    }
    base.update(overrides)
    return SchedulerStats(**base)  # type: ignore[arg-type]


def test_synthesize_is_a_dispatchable_loop_task() -> None:
    """The scheduler may name a non-terminal overview firing."""
    assert TaskType.SYNTHESIZE in ALLOWED_LOOP_TASKS
    stats = _settled_stats()
    decision = validate_decision(decide_next_task(stats, _EXTENDED), stats)
    assert decision.next_task is TaskType.SYNTHESIZE


def test_the_cheaper_tiers_never_fire_it() -> None:
    """One firing is one very large call plus up to two escalation rungs."""
    stats = _settled_stats()
    assert _check_research_overview_cadence(stats, _STANDARD) is None
    express = Budget(max_iterations=1, max_llm_calls=1200)
    assert _check_research_overview_cadence(stats, express) is None


def test_it_does_not_fire_every_cycle() -> None:
    """The cadence is work cycles since the last firing, not every pass."""
    stats = _settled_stats(iterations_since_research_overview=1)
    assert _check_research_overview_cadence(stats, _EXTENDED) is None


def test_a_firing_that_just_ran_cannot_immediately_re_fire() -> None:
    """The anchor resets as the decision is taken, so the step terminates.

    The overview is not a work task, so it never advances the iteration
    counter itself; without the anchor reset the check would hold at every
    remaining loop point and the run would never make progress again.
    """
    stats = _settled_stats(iterations_since_research_overview=0)
    assert _check_research_overview_cadence(stats, _EXTENDED) is None


def test_the_last_iteration_terminates_rather_than_firing() -> None:
    """The cadence sits below both terminations, unlike meta-review's.

    An interim overview is read by the *next* generate cycle, so firing it
    on the iteration that ends the run buys the largest prompt in the
    system for a reader that never arrives.
    """
    ultra = Budget(max_iterations=4, max_llm_calls=14000)
    stats = _settled_stats(iteration=4)
    assert decide_next_task(stats, ultra).terminate is True


def test_cadence_never_outranks_a_review_backlog() -> None:
    """Periodic synthesis sits below every required transition."""
    stats = _settled_stats(unreviewed_count=3)
    assert decide_next_task(stats, _EXTENDED).next_task is TaskType.REFLECT


def test_a_periodic_firing_returns_to_the_loop_point() -> None:
    """Both execution paths share one resolver, so neither can drift."""
    state = make_state(next_task=TaskType.SYNTHESIZE.value)
    assert route_after_research_overview(state) == "orchestrator"
    assert next_task_type("research_overview", state) == "orchestrator"


def test_the_terminal_firing_still_ends_the_run() -> None:
    """TERMINATE's own synthesis is unchanged: it is the last node."""
    state = make_state(next_task=TaskType.TERMINATE.value)
    assert route_after_research_overview(state) is None
    assert next_task_type("research_overview", state) is None


def test_synthesize_enters_at_the_overview_node() -> None:
    """The task value routes to the node that writes the overview."""
    assert TASK_ROUTES[TaskType.SYNTHESIZE.value] == "research_overview"


def test_the_interim_overview_reaches_generation() -> None:
    """The feedback edge itself: what a firing wrote is read as context."""
    written = build_interim_overview(
        {
            "overview": {
                "research_directions": [
                    {"title": "Releasing the myeloid brake"}
                ]
            },
            "open_questions": ["What sets the reversal threshold?"],
        }
    )
    block = format_interim_overview(make_state(interim_overview=written))

    assert "Releasing the myeloid brake" in block
    assert "What sets the reversal threshold?" in block
    assert "interim research overview" in block.lower()


def test_no_interim_overview_renders_nothing() -> None:
    """Before the first firing generation sees exactly what it saw before."""
    assert format_interim_overview(make_state()) == ""
