"""One DecideNextSteps pass may stack several follow-up tasks (FIX-3).

Listing 01's ``DecideNextSteps`` is one **unconditional** statement --
``RunTournamentBatch``, queued on every pass with no ``IF`` at all --
followed by three **independent** ``IF``s: evolve when quality stopped
improving (L57-60), ``GenerateSystemFeedback`` when enough time has
passed (L61-64), and ``GenerateFinalResearchOverview`` plus its
``RETURN FinalReport`` (L65-69). Ours collapsed all four into a
single-winner precedence chain: one loop point produced exactly one task,
so whichever branch won suppressed the rest.

The two *maintenance* branches stack, in the listing's own order:
meta-review's system feedback first, then the periodic research overview
that reads it. The two *work* branches do not, and cannot: ``rank`` and
``evolve`` are multi-node chains whose fixed successor is the loop point
itself (``rank -> safety_screen -> ... -> ranking -> orchestrator``,
``evolve -> meta_review -> evolve -> review -> ... -> orchestrator``), so
a companion form of either could not hand control back to the primary --
in this topology they *are* the primary.

The assertions are about control-flow shape: that a pass produces several
tasks in order, that the primary's own identity survives (the settlement
and iteration accounting all key on it), that the terminal decision is
never wrapped, and that the companion chain's routers walk companion to
companion to primary.
"""

from __future__ import annotations

from typing import cast

from langgraph.graph import StateGraph

from co_scientist.agents.meta_review.research_overview_degrade import (
    is_interim_firing,
)
from co_scientist.agents.supervisor.orchestrator_bookkeeping import (
    _research_overview_anchor,
)
from co_scientist.checkpoint import (
    restore_workflow_state,
    serialize_workflow_state,
)
from co_scientist.generator.graph import (
    _OVERVIEW_ROUTE_NODES,
    _add_workflow_edges,
    _add_workflow_nodes,
    _route_after_meta_review,
    _route_after_research_overview,
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
from co_scientist.state import WorkflowState
from co_scientist.task_runtime import plan_portfolio
from tests._state import make_state

# Extended's own ceiling: the smallest tier that funds a periodic overview
# (``policy_cadence.RESEARCH_OVERVIEW_MIN_LLM_CALLS``).
_BUDGET = Budget(max_iterations=4, max_llm_calls=7000)

# Express's ceiling, below that gate: the overview companion never fires.
_CHEAP_BUDGET = Budget(max_iterations=4, max_llm_calls=1200)


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
    decision = stack_companions(
        decide_next_task(stats, _BUDGET), stats, _BUDGET
    )
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
    decision = stack_companions(
        decide_next_task(stats, _BUDGET), stats, _BUDGET
    )
    assert decision.next_task is TaskType.RANK
    assert stacked_task_values(decision.queue_actions)


def test_a_terminating_decision_is_never_wrapped() -> None:
    """A stop carries no companion; ``terminate`` gates too much to touch.

    The spent-budget stop is checked above the cadence step, so the pass
    really does reach ``stack_companions`` with the cadence due.
    """
    stats = _due_stats(unreviewed_count=0, llm_calls=99)
    spent = Budget(max_iterations=4, max_llm_calls=1)
    decision = stack_companions(decide_next_task(stats, spent), stats, spent)
    assert decision.terminate
    assert not stacked_task_values(decision.queue_actions)


def test_evolve_is_not_stacked_because_it_already_runs_meta_review() -> None:
    """EVOLVE enters at the meta_review node; stacking would double it."""
    evolve = SupervisorDecision(
        next_task=TaskType.EVOLVE, reason="evolution out-yields generation"
    )
    stacked = stack_companions(evolve, _due_stats(), _BUDGET)
    assert not stacked_task_values(stacked.queue_actions)


def test_nothing_is_stacked_when_the_cadence_is_not_due() -> None:
    """The companion rides the same predicate as the standalone step."""
    stats = _due_stats(feedback_since_meta_review=0)
    decision = stack_companions(
        decide_next_task(stats, _BUDGET), stats, _BUDGET
    )
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


def _overview_due(**overrides: object) -> SchedulerStats:
    """Stats with both periodic branches due at the same loop point."""
    return _due_stats(iterations_since_research_overview=2, **overrides)


def test_one_pass_stacks_both_periodic_branches() -> None:
    """Meta-review then the overview, in the listing's own order.

    L61's ``GenerateSystemFeedback`` is queued before L65's
    ``GenerateFinalResearchOverview``, and the overview is drafted from
    the critique that feedback just synthesized.
    """
    stats = _overview_due()
    decision = stack_companions(
        decide_next_task(stats, _BUDGET), stats, _BUDGET
    )
    assert decision.next_task is TaskType.REFLECT
    assert stacked_task_values(decision.queue_actions) == (
        TaskType.META_REVIEW.value,
        TaskType.SYNTHESIZE.value,
    )


def test_the_overview_companion_is_gated_by_the_tier_ceiling() -> None:
    """Express and standard buy the largest prompt in the system never.

    Same gate the standalone step reads
    (``policy_cadence.RESEARCH_OVERVIEW_MIN_LLM_CALLS``), so stacking
    cannot smuggle a firing into a tier that declined to fund one.
    """
    stats = _overview_due()
    decision = stack_companions(
        decide_next_task(stats, _CHEAP_BUDGET), stats, _CHEAP_BUDGET
    )
    assert stacked_task_values(decision.queue_actions) == (
        TaskType.META_REVIEW.value,
    )


def test_a_companion_is_never_stacked_onto_its_own_primary() -> None:
    """A SYNTHESIZE primary already runs the overview node."""
    synthesize = SupervisorDecision(
        next_task=TaskType.SYNTHESIZE, reason="periodic overview is due"
    )
    stacked = stack_companions(synthesize, _overview_due(), _BUDGET)
    assert stacked_task_values(stacked.queue_actions) == (
        TaskType.META_REVIEW.value,
    )


def test_the_overview_never_runs_ahead_of_a_critique_being_written() -> None:
    """A META_REVIEW primary defers the overview rather than inverting it.

    The overview is drafted *from* the critique (listing order L961-964
    before L966-971), so stacking it ahead of a pass that is about to
    write one would hand it the previous cycle's. Deferring costs
    nothing: the cadence anchor only resets when a firing is scheduled.
    """
    meta_review = SupervisorDecision(
        next_task=TaskType.META_REVIEW, reason="periodic feedback is due"
    )
    stacked = stack_companions(meta_review, _overview_due(), _BUDGET)
    assert not stacked_task_values(stacked.queue_actions)


def test_the_routers_walk_companion_to_companion_to_primary() -> None:
    """Both stacked nodes run in order, then the primary the pass chose."""
    state = make_state(next_task=TaskType.REFLECT.value)
    state["supervisor_queue_actions"] = [
        {"action": "enqueue", "task_type": TaskType.META_REVIEW.value},
        {"action": "enqueue", "task_type": TaskType.SYNTHESIZE.value},
    ]
    assert _route_next_task(state) == "meta_review"
    assert _route_after_meta_review(state) == "research_overview"
    assert _route_after_research_overview(state) == "review"
    assert plan_portfolio("meta_review", state) == [
        "meta_review",
        "research_overview",
        "review",
    ]


def test_a_stacked_overview_is_an_interim_firing() -> None:
    """The stacked firing must not publish the terminal document.

    ``is_interim_firing`` keyed on ``next_task == synthesize`` alone,
    which a stacked pass never sets -- the primary keeps that field. Read
    that way the companion would run the full terminal synthesis: the
    accuracy-review loop, the knowledge-base calls, a 95% progress
    emission mid-run, and a published ``research_overview`` the report
    would then carry from the middle of the run.
    """
    state = make_state(next_task=TaskType.REFLECT.value)
    state["supervisor_queue_actions"] = [
        {"action": "enqueue", "task_type": TaskType.SYNTHESIZE.value}
    ]
    assert is_interim_firing(state)
    # And it hands over to the primary rather than ending the run: None
    # here would finalize the report from the middle of a cycle.
    assert _route_next_task(state) == "research_overview"
    assert _route_after_research_overview(state) == "review"


def test_a_terminal_firing_is_still_terminal() -> None:
    """No companion, so the overview publishes and the graph ends."""
    state = make_state(next_task=TaskType.TERMINATE.value)
    assert not is_interim_firing(state)
    assert _route_after_research_overview(state) is None


def test_a_stacked_overview_resets_its_own_cadence_anchor() -> None:
    """Otherwise the companion re-stacks on every remaining loop point.

    The anchor reset is what terminates the step: the overview is not a
    work task, so nothing else moves the gap off its threshold.
    """
    stats = _overview_due(iteration=3)
    decision = stack_companions(
        decide_next_task(stats, _BUDGET), stats, _BUDGET
    )
    book = {"iteration_at_last_research_overview": 0}
    assert _research_overview_anchor(book, stats, decision) == 3


def test_the_compiled_graph_accepts_every_companion_route() -> None:
    """A widened router needs a widened path map, or compile rejects it.

    ``add_conditional_edges`` takes an explicit path map, so a node the
    router can now return but the map does not list is a run-time
    rejection rather than a review-time one.
    """
    workflow = StateGraph(WorkflowState)
    _add_workflow_nodes(workflow, False)
    _add_workflow_edges(workflow, False)
    assert workflow.compile() is not None
    assert set(_OVERVIEW_ROUTE_NODES) >= {"meta_review", "orchestrator"}


def test_the_stacked_list_survives_a_checkpoint_round_trip() -> None:
    """Every reader of the companion list runs after a restore.

    Only the orchestrator's own commit reads it on fresh in-memory
    state; the routers, ``is_interim_firing`` and ``plan_portfolio``'s
    resolver all read it from inside a companion task, on state restored
    from the orchestrator's checkpoint. Dropped there, a durable pass
    would route past the overview silently -- and a resumed one would
    read the stacked firing as terminal and finalize the report from the
    middle of a cycle. ``checkpoint._TRANSIENT_CONTROL_KEYS`` is
    hand-maintained, so this pins the key against it.
    """
    state = make_state(next_task=TaskType.REFLECT.value)
    state["supervisor_queue_actions"] = [
        {"action": "enqueue", "task_type": TaskType.META_REVIEW.value},
        {"action": "enqueue", "task_type": TaskType.SYNTHESIZE.value},
    ]
    restored = restore_workflow_state(
        serialize_workflow_state(dict(state), last_event_seq=0)
    )
    assert stacked_task_values(restored["supervisor_queue_actions"]) == (
        TaskType.META_REVIEW.value,
        TaskType.SYNTHESIZE.value,
    )
    assert is_interim_firing(cast(WorkflowState, restored))
    assert _route_after_meta_review(cast(WorkflowState, restored)) == (
        "research_overview"
    )
