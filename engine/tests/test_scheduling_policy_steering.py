"""Offline contracts for scheduling policy steering."""

from __future__ import annotations

from typing import cast

from langgraph.graph import StateGraph

from co_scientist.agents.meta_review.research_overview import (
    build_interim_overview,
    format_interim_overview,
    is_interim_firing,
)
from co_scientist.agents.supervisor.orchestrator import (
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
)
from co_scientist.scheduling import (
    ALLOWED_LOOP_TASKS,
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    TerminationReason,
    decide_next_task,
    stacked_task_values,
)
from co_scientist.scheduling.policy import (
    _check_research_overview_cadence,
    stack_companions,
    validate_decision,
)
from co_scientist.state import WorkflowState
from co_scientist.task_runtime import next_task_type, plan_portfolio
from co_scientist.workflow_topology import (
    TASK_ROUTES,
    route_after_meta_review,
    route_after_research_overview,
    route_next_task,
)
from tests._state import BUDGET, healthy_stats, make_state

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


def test_owed_review_outranks_budget_termination() -> None:
    stats = healthy_stats(owed_review_count=1, tasks_run=100)

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.REFLECT
    assert "review" in decision.reason


def test_owed_review_refuses_to_override_the_llm_call_ceiling() -> None:
    # The one exhaustion reason this override may never buy against: see
    # scheduling.policy_budget._check_owed_review's docstring for why a
    # forced REFLECT here would crash rather than run.
    stats = healthy_stats(owed_review_count=1, llm_calls=1000)

    decision = decide_next_task(stats, BUDGET)

    assert decision.terminate
    assert decision.termination_reason is TerminationReason.BUDGET


def test_owed_review_stays_inert_while_the_budget_has_room() -> None:
    # A healthy run must never pay for this override: the marker it would
    # spend is permanent, so firing here would exhaust it on an ordinary
    # cycle long before a genuinely budget-exhausting admission needed one.
    stats = healthy_stats(owed_review_count=1)

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.GENERATE


def test_safety_block_outranks_owed_review() -> None:
    stats = healthy_stats(
        owed_review_count=1, tasks_run=100, safety_blocked=True
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.terminate
    assert decision.termination_reason is TerminationReason.SAFETY


def test_steering_outranks_owed_review() -> None:
    stats = healthy_stats(
        owed_review_count=1, tasks_run=100, pending_steering=True
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.GENERATE
    assert "steering" in decision.reason


def test_owed_coverage_outranks_owed_review() -> None:
    # Both can fire on the same exhausted-budget cycle; owed coverage keeps
    # its existing precedence over every budget-adjacent check below it.
    stats = healthy_stats(
        rankable_count=3,
        unmatched_rankable_count=1,
        owed_coverage_rounds=1,
        owed_review_count=1,
        tasks_run=100,
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.RANK


def test_zero_owed_review_leaves_budget_termination_alone() -> None:
    stats = healthy_stats(owed_review_count=0, llm_calls=1000)

    decision = decide_next_task(stats, BUDGET)

    assert decision.terminate
    assert decision.termination_reason is TerminationReason.BUDGET


def test_budget_outranks_ordinary_backlog_without_an_owed_review() -> None:
    # Restates the existing test_budget_outranks_backlog with the new field
    # present and zero: an unreviewed backlog alone (nothing specifically
    # owed the override) still yields to a spent budget exactly as before.
    stats = healthy_stats(
        unreviewed_count=5, owed_review_count=0, llm_calls=1000
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.terminate
    assert decision.termination_reason is TerminationReason.BUDGET


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
    assert route_next_task(state) == "meta_review"
    assert route_after_meta_review(state) == "review"
    assert plan_portfolio("meta_review", state) == ["meta_review", "review"]


def test_an_unstacked_pass_routes_straight_to_the_primary() -> None:
    """Without a companion the loop point is exactly as it was."""
    state = make_state(next_task=TaskType.REFLECT.value)
    assert route_next_task(state) == "review"


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
    assert route_next_task(state) == "meta_review"
    assert route_after_meta_review(state) == "research_overview"
    assert route_after_research_overview(state) == "review"
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
    assert route_next_task(state) == "research_overview"
    assert route_after_research_overview(state) == "review"


def test_a_terminal_firing_is_still_terminal() -> None:
    """No companion, so the overview publishes and the graph ends."""
    state = make_state(next_task=TaskType.TERMINATE.value)
    assert not is_interim_firing(state)
    assert route_after_research_overview(state) is None


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
    assert route_after_meta_review(cast(WorkflowState, restored)) == (
        "research_overview"
    )


def test_steering_outranks_budget_exhaustion() -> None:
    """Pending steering buys one cycle even against an exhausted budget.

    HITL-STEERING-001 / HITL-MANUAL-HYP-001: a scientist contribution
    admitted the same cycle the budget runs out (an admission also queues
    a steering message; see app.runs.contrib._steer_and_continue) must not
    be silently dropped by an immediate termination -- _check_steering
    (step 2) outranks _budget_termination (step 4), so the message still
    gets its one GENERATE cycle before the run may stop. Note this closes
    only the "steering silently dropped" half: it does not by itself
    guarantee the admitted idea gets *reviewed* before a later cycle
    terminates on the same exhausted budget -- see
    test_scheduling_policy.py::test_budget_outranks_backlog, which shows
    an exhausted budget still wins over an unreviewed backlog once no
    further steering remains to defer it.
    """
    budget = Budget(max_iterations=100, max_llm_calls=10)
    stats = healthy_stats(llm_calls=10, pending_steering=True)
    decision = decide_next_task(stats, budget)
    assert decision.next_task is TaskType.GENERATE
    assert not decision.terminate
