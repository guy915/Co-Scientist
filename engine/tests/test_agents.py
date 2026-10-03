"""Offline contracts for agents."""

from __future__ import annotations

import ast
import itertools
import pathlib
from collections.abc import Iterator
from typing import Any, cast

import pytest
from langgraph.graph import END, START, StateGraph
from litellm.exceptions import APIError

import co_scientist.llm as llm
from co_scientist import agents, constants, task_runtime
from co_scientist.agents import NODE_REGISTRY
from co_scientist.agents.generation.generate import generate_node
from co_scientist.agents.meta_review import meta_review as mr
from co_scientist.agents.meta_review import research_overview as ro
from co_scientist.agents.proximity import proximity as px
from co_scientist.agents.reflection.review import review_node
from co_scientist.agents.supervisor.supervisor import supervisor_node
from co_scientist.checkpoint import (
    restore_workflow_state,
    serialize_workflow_state,
)
from co_scientist.constants import INITIAL_ELO_RATING
from co_scientist.exceptions import (
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
    LLMTimeoutError,
)
from co_scientist.generator import GeneratorOptions, HypothesisGenerator
from co_scientist.generator.graph import (
    _add_workflow_edges,
    _add_workflow_nodes,
)
from co_scientist.models import Hypothesis, HypothesisOrigin
from co_scientist.scheduling import TaskType
from co_scientist.state import WorkflowState
from co_scientist.task_runtime import next_task_type
from co_scientist.workflow_topology import (
    TASK_ROUTES,
    WORKFLOW_ROUTES,
    LiteratureGated,
    literature_review_nodes,
)
from tests._llm_fake import install_fake_llm
from tests._state import (
    ABSENT,
    build_graph,
    decision_states,
    graph_successor,
    make_hypothesis,
    make_review,
    make_state,
)

# The 14 durable node keys, frozen on purpose: they are persisted in the
# durable task queue and checkpoints as ``engine.node.<key>``, so renaming
# one is a data migration, not a refactor. This literal pin is intentional.
FROZEN_DURABLE_NODE_KEYS = {
    "supervisor",
    "generate",
    "review",
    "comprehensive_reflection",
    "safety_screen",
    "ranking",
    "deep_verification",
    "orchestrator",
    "meta_review",
    "evolve",
    "proximity",
    "research_overview",
    "literature_review",
    "reflection",
}


def _compiled_graph_node_keys() -> set[str]:
    """Compile the full workflow graph and return its registered node keys."""
    workflow = StateGraph(WorkflowState)
    _add_workflow_nodes(workflow, enable_literature_review_node=True)
    _add_workflow_edges(workflow, enable_literature_review_node=True)
    compiled = workflow.compile()
    return set(compiled.get_graph().nodes) - {"__start__", "__end__"}


def test_registry_pins_the_frozen_durable_node_keys() -> None:
    """NODE_REGISTRY carries exactly the frozen persisted key strings."""
    assert set(agents.NODE_REGISTRY) == FROZEN_DURABLE_NODE_KEYS


def test_graph_registry_and_task_runtime_agree() -> None:
    """Compiled graph keys == registry keys == durable TASK_NODES keys."""
    registry_keys = set(agents.NODE_REGISTRY)
    assert _compiled_graph_node_keys() == registry_keys
    assert set(task_runtime.TASK_NODES) == registry_keys


def test_node_to_agent_is_projected_from_the_registry() -> None:
    """NODE_TO_AGENT covers every registry key with the spec's agent."""
    assert set(agents.NODE_TO_AGENT) == set(agents.NODE_REGISTRY)
    for key, spec in agents.NODE_REGISTRY.items():
        assert agents.NODE_TO_AGENT[key] == spec.agent


def test_every_agent_owns_at_least_one_node() -> None:
    """The six agents plus supervisor and safety each own a node."""
    owners = set(agents.NODE_TO_AGENT.values())
    assert owners == {
        "supervisor",
        "generation",
        "reflection",
        "ranking",
        "evolution",
        "proximity",
        "meta_review",
        "safety",
    }


def test_registry_holds_the_real_node_callables() -> None:
    """NODE_REGISTRY and TASK_NODES reference the actual node callables."""
    assert agents.NODE_REGISTRY["supervisor"].node is supervisor_node
    assert agents.NODE_REGISTRY["generate"].node is generate_node
    assert agents.NODE_REGISTRY["review"].node is review_node
    assert task_runtime.TASK_NODES["generate"] is generate_node


def test_agent_modules_reexport_the_real_node_callables() -> None:
    """Each agent module re-exports the actual node callable, not a copy."""
    assert agents.supervisor.supervisor_node is supervisor_node
    assert agents.generation.generate_node is generate_node
    assert agents.reflection.review_node is review_node


# The two shapes the incident produced, in the order it produced them.
_TIMEOUT = LLMTimeoutError(
    "LLM call to openrouter/minimax/minimax-m3:free exceeded 600.0s"
)
_UPSTREAM = APIError(
    status_code=500,
    message="OpenrouterException - Upstream error from Nvidia: overloaded",
    llm_provider="openrouter",
    model="minimax/minimax-m3:free",
)

# The two the durable worker answers itself -- a park waits for a clock and
# a spent ceiling terminates the run, so neither may be swallowed here.
_CONTROL_FLOW: list[Exception] = [
    LLMCallBudgetExceededError(count=2501, ceiling=2500),
    LLMRateLimitParkError(resume_at=1.0, reason="message_per_day"),
]


def _raiser(error: Exception) -> Any:
    """Return an async stand-in for ``call_llm_json`` that raises ``error``."""

    async def _call(*_: Any, **__: Any) -> dict[str, Any]:
        raise error

    return _call


def _overview_state(**overrides: Any) -> Any:
    """A state whose publishable pool reaches the synthesis call."""
    return make_state(
        hypotheses=[make_hypothesis(text="H", elo_rating=1700)],
        research_goal="g",
        supervisor_model_name="test/model",
        meta_review={},
        articles=[],
        **overrides,
    )


@pytest.mark.parametrize("error", [_TIMEOUT, _UPSTREAM])
async def test_overview_degrades_on_an_unreachable_provider(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """A stalled or failing provider yields the empty overview, not a raise."""
    monkeypatch.setattr(ro, "call_llm_json", _raiser(error))
    state = _overview_state()

    out = await ro.research_overview_node(state)

    assert out["research_overview"] == {}
    assert state["degraded_nodes"] == ["research_overview"]


@pytest.mark.parametrize("error", _CONTROL_FLOW)
async def test_overview_reraises_the_worker_owned_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """A park and a spent call ceiling must still reach the worker."""
    monkeypatch.setattr(ro, "call_llm_json", _raiser(error))

    with pytest.raises(type(error)):
        await ro.research_overview_node(_overview_state())


async def test_interim_overview_failure_is_not_a_degraded_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A periodic firing publishes nothing, so it labels no report section.

    ``degraded_sections`` names a blank section of the finished report.
    The interim firing writes no document -- the terminal one still can --
    so recording it here would tag an overview that came out fine.
    """
    monkeypatch.setattr(ro, "call_llm_json", _raiser(_UPSTREAM))
    state = _overview_state(next_task=TaskType.SYNTHESIZE.value)

    out = await ro.research_overview_node(state)

    assert "interim_overview" not in out
    assert state.get("degraded_nodes", []) == []


def _reviewed_state() -> Any:
    """A state carrying one reviewed hypothesis, so meta-review calls out."""
    hypothesis = make_hypothesis(text="H")
    hypothesis.reviews = [make_review()]
    return make_state(
        hypotheses=[hypothesis],
        research_goal="g",
        supervisor_model_name="test/model",
    )


@pytest.mark.parametrize("error", [_TIMEOUT, _UPSTREAM])
async def test_meta_review_degrades_on_an_unreachable_provider(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """Meta-review falls back to its empty synthesis rather than failing.

    Its summary renders into the report, so the degraded one must not
    borrow the no-reviews branch's wording: this run had its reviews.
    """
    monkeypatch.setattr(mr, "call_llm_json", _raiser(error))
    state = _reviewed_state()

    out = await mr.meta_review_node(state)

    assert out["meta_review"]["summary"] == (
        "Meta-review synthesis was unavailable for this cycle"
    )
    assert out["meta_review"]["strategic_recommendations"] == []
    assert state["degraded_nodes"] == ["meta_review"]


@pytest.mark.parametrize("error", _CONTROL_FLOW)
async def test_meta_review_reraises_the_worker_owned_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """The same two errors keep propagating out of meta-review."""
    monkeypatch.setattr(mr, "call_llm_json", _raiser(error))

    with pytest.raises(type(error)):
        await mr.meta_review_node(_reviewed_state())


def _pair_state() -> Any:
    """Two hypotheses, the minimum proximity needs to cluster anything."""
    return make_state(
        hypotheses=[make_hypothesis(text="A"), make_hypothesis(text="B")],
        research_goal="g",
        model_name="test/model",
    )


@pytest.mark.parametrize("error", [_TIMEOUT, _UPSTREAM])
async def test_proximity_degrades_on_an_unreachable_provider(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """Proximity skips deduplication for the cycle instead of failing."""
    monkeypatch.setattr(px, "call_llm_json", _raiser(error))
    state = _pair_state()

    out = await px.proximity_node(state)

    assert len(out["hypotheses"]) == 2
    assert state["degraded_nodes"] == ["proximity_analysis"]


@pytest.mark.parametrize("error", _CONTROL_FLOW)
async def test_proximity_reraises_the_worker_owned_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """The same two errors keep propagating out of proximity."""
    monkeypatch.setattr(px, "call_llm_json", _raiser(error))

    with pytest.raises(type(error)):
        await px.proximity_node(_pair_state())


# Each node with the state that reaches its LLM call. On the durable path
# the same provider failure goes two ways, decided by whether the task
# running the node still holds a retry: the tests above leave the flag
# unset, which is the graph path and always degrades.
_NODE_CASES = [
    pytest.param(
        ro, ro.research_overview_node, _overview_state, id="research_overview"
    ),
    pytest.param(mr, mr.meta_review_node, _reviewed_state, id="meta_review"),
    pytest.param(px, px.proximity_node, _pair_state, id="proximity"),
]


@pytest.mark.parametrize(("module", "node", "build_state"), _NODE_CASES)
@pytest.mark.parametrize("error", [_TIMEOUT, _UPSTREAM])
async def test_a_provider_failure_propagates_while_attempts_remain(
    monkeypatch: pytest.MonkeyPatch,
    module: Any,
    node: Any,
    build_state: Any,
    error: Exception,
) -> None:
    """A retry the task still holds is worth more than a blank section.

    Extended run bc77950f met the same provider trouble as 49a509b0 and
    published a full overview on its third durable attempt. Degrading on
    the first would have thrown those two attempts away.
    """
    monkeypatch.setattr(module, "call_llm_json", _raiser(error))
    state = build_state()
    state["durable_retries_remain"] = True

    with pytest.raises(type(error)):
        await node(state)

    assert state.get("degraded_nodes", []) == []


@pytest.mark.parametrize(("module", "node", "build_state"), _NODE_CASES)
@pytest.mark.parametrize("error", [_TIMEOUT, _UPSTREAM])
async def test_the_last_durable_attempt_degrades_instead(
    monkeypatch: pytest.MonkeyPatch,
    module: Any,
    node: Any,
    build_state: Any,
    error: Exception,
) -> None:
    """With no retry left, raising would settle the run and lose the report."""
    monkeypatch.setattr(module, "call_llm_json", _raiser(error))
    state = build_state()
    state["durable_retries_remain"] = False

    await node(state)

    assert len(state["degraded_nodes"]) == 1


@pytest.mark.parametrize("error", _CONTROL_FLOW)
@pytest.mark.parametrize("retries_remain", [True, False])
async def test_control_flow_errors_reraise_whatever_the_attempt(
    monkeypatch: pytest.MonkeyPatch, error: Exception, retries_remain: bool
) -> None:
    """Neither error is "this call failed", so no attempt count absorbs them."""
    monkeypatch.setattr(ro, "call_llm_json", _raiser(error))
    state = _overview_state(durable_retries_remain=retries_remain)

    with pytest.raises(type(error)):
        await ro.research_overview_node(state)

    assert state.get("degraded_nodes", []) == []


async def test_the_interim_firing_also_spends_its_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The periodic firing shares the task's retry budget, so it uses it.

    It labels no report section either way (the test above), but a retry
    it declines to take is one the terminal firing never gets.
    """
    monkeypatch.setattr(ro, "call_llm_json", _raiser(_UPSTREAM))
    state = _overview_state(
        next_task=TaskType.SYNTHESIZE.value, durable_retries_remain=True
    )

    with pytest.raises(APIError):
        await ro.research_overview_node(state)


def test_the_attempt_flag_never_rides_a_checkpoint() -> None:
    """It describes one durable attempt, so persisting it would misread.

    A checkpoint written on attempt 1 is restored by attempt 2 and by
    every later node; carrying "retries remain" into them would report
    the wrong task's budget.
    """
    envelope = serialize_workflow_state(
        _overview_state(durable_retries_remain=True), last_event_seq=0
    )

    assert "durable_retries_remain" not in envelope["state"]
    assert "durable_retries_remain" not in restore_workflow_state(envelope)


# The checkpoints each node emits, in emission order. Nodes absent here are
# covered by _EXEMPT_NODES below; a node the walk visits that is in neither
# fails test_every_walked_node_is_covered_or_exempt.
_NODE_CHECKPOINTS: dict[str, tuple[int, ...]] = {
    "supervisor": (
        constants.PROGRESS_SUPERVISOR_START,
        constants.PROGRESS_SUPERVISOR_COMPLETE,
    ),
    "generate": (
        constants.PROGRESS_GENERATE_START,
        constants.PROGRESS_GENERATE_COMPLETE,
    ),
    "reflection": (
        constants.PROGRESS_REFLECTION_START,
        constants.PROGRESS_REFLECTION_COMPLETE,
    ),
    "review": (
        constants.PROGRESS_REVIEW_START,
        constants.PROGRESS_REVIEW_COMPLETE,
    ),
    "safety_screen": (
        constants.PROGRESS_SAFETY_SCREEN_START,
        constants.PROGRESS_SAFETY_SCREEN_COMPLETE,
    ),
    "deep_verification": (
        constants.PROGRESS_DEEP_VERIFICATION_START,
        constants.PROGRESS_DEEP_VERIFICATION_COMPLETE,
    ),
    "ranking": (
        constants.PROGRESS_TOURNAMENT_START,
        constants.PROGRESS_TOURNAMENT_COMPLETE,
    ),
    "orchestrator": (constants.PROGRESS_ORCHESTRATOR_DECISION,),
    "proximity": (
        constants.PROGRESS_PROXIMITY_START,
        constants.PROGRESS_PROXIMITY_COMPLETE,
    ),
    "meta_review": (
        constants.PROGRESS_META_REVIEW_START,
        constants.PROGRESS_META_REVIEW_COMPLETE,
    ),
    "evolve": (
        constants.PROGRESS_EVOLVE_START,
        constants.PROGRESS_EVOLVE_COMPLETE,
    ),
    "research_overview": (
        constants.PROGRESS_RESEARCH_OVERVIEW_START,
        constants.PROGRESS_RESEARCH_OVERVIEW_COMPLETE,
    ),
}

# Walked nodes that emit no checkpoint from constants/__init__.py.
_EXEMPT_NODES = {
    # Emits no PROGRESS_* checkpoint at all.
    "comprehensive_reflection",
    # Its progress values are hardcoded fractions (0.1-0.2) in its node
    # module -- a 0-1 vs 0-100 scale mismatch that predates this invariant
    # and lives outside constants/__init__.py, so it cannot join the walk yet.
    "literature_review",
}


def _first_pass_order(mcp_available: bool) -> list[str]:
    """The order a run's nodes first execute, from the successor table.

    Walks ``next_task_type`` the way the durable worker does: the fixed
    pipeline out of the supervisor, then the orchestrator's routing. The
    scheduling policy shapes the loop decisions along the way: a proximity
    refresh is owed -- and therefore scheduled -- before any generate/evolve
    fall-through on the first pass (``policy_checks._check_proximity_refresh``
    outranks the yield choice), and the evolve task enters at meta_review.
    The walk stops where the evolve task re-enters the review pipeline,
    since that is the second cycle's first step, not the first pass's.

    Args:
        mcp_available: Whether the MCP-gated literature-review path is on.

    Returns:
        Node names in first-execution order.
    """
    state = make_state(mcp_available=mcp_available)

    def step(completed: str) -> str:
        """One successor hop, rejecting the terminal None mid-walk."""
        successor = next_task_type(completed, state)
        assert successor is not None
        return successor

    order: list[str] = ["supervisor"]
    node = "supervisor"
    while node != "orchestrator":
        node = step(node)
        order.append(node)

    state["next_task"] = "proximity"
    node = step("orchestrator")
    order.append(node)
    node = step(node)  # proximity -> orchestrator
    order.append(node)

    state["next_task"] = "evolve"
    node = step("orchestrator")
    order.append(node)  # meta_review
    node = step(node)
    order.append(node)  # evolve

    state["next_task"] = "terminate"
    order.append(step("orchestrator"))  # research_overview
    return order


def test_walk_is_the_first_pass_it_claims_to_cover() -> None:
    """Guards the walk itself against a topology change shrinking it.

    If the walk silently dropped part of the first pass, the monotonicity
    test below would keep passing against a shorter order and hide a
    regression in the part it lost.
    """
    assert _first_pass_order(mcp_available=True) == [
        "supervisor",
        "literature_review",
        "generate",
        "reflection",
        "review",
        "comprehensive_reflection",
        "safety_screen",
        "deep_verification",
        "ranking",
        "orchestrator",
        "proximity",
        "orchestrator",
        "meta_review",
        "evolve",
        "research_overview",
    ]
    assert _first_pass_order(mcp_available=False) == [
        "supervisor",
        "generate",
        "review",
        "comprehensive_reflection",
        "safety_screen",
        "deep_verification",
        "ranking",
        "orchestrator",
        "proximity",
        "orchestrator",
        "meta_review",
        "evolve",
        "research_overview",
    ]


def test_first_pass_progress_never_decreases() -> None:
    """Reported progress never moves backward on a run's first pass.

    Every checkpoint each node emits, in the order the durable path first
    reaches them, must be at least the previous one: a smaller value after
    a larger one is the run reporting that it got less far than it just
    said. The walk covers the loop point on both sides of proximity
    (ranking -> orchestrator -> proximity -> orchestrator), so the seams a
    backward-stepping band would trip on are in the sequence twice.
    """
    for mcp_available in (True, False):
        values: list[int] = []
        for node in _first_pass_order(mcp_available):
            values.extend(_NODE_CHECKPOINTS.get(node, ()))

        decreases = [
            (before, after)
            for before, after in itertools.pairwise(values)
            if after < before
        ]
        assert not decreases, (
            f"progress steps backward (mcp_available={mcp_available}): "
            f"{decreases}"
        )


def test_every_checkpoint_starts_before_it_completes() -> None:
    """A node's start checkpoint never reports more than its completion."""
    for name, checkpoints in _NODE_CHECKPOINTS.items():
        if len(checkpoints) < 2:
            continue
        start, complete = checkpoints[0], checkpoints[-1]
        assert start <= complete, name


def test_every_walked_node_is_covered_or_exempt() -> None:
    """A node the walk visits must join the invariant or be exempted by name.

    Without this, a new node with its own checkpoints could enter the
    topology and slip past the monotonicity check simply by not being in
    ``_NODE_CHECKPOINTS``.
    """
    walked = set(_first_pass_order(True)) | set(_first_pass_order(False))
    uncovered = walked - set(_NODE_CHECKPOINTS) - _EXEMPT_NODES
    assert not uncovered, (
        f"walked nodes with no checkpoint coverage and no exemption: "
        f"{sorted(uncovered)}"
    )


def test_every_declared_progress_constant_is_pinned() -> None:
    """A new PROGRESS_* constant must join the invariant, not slip past it.

    Discovery is by value, which a constant sharing a pinned value could
    evade; the walk-coverage test above is the finer guard, and this one
    catches the common case of a new constant at a fresh value.
    """
    pinned = {
        value
        for checkpoints in _NODE_CHECKPOINTS.values()
        for value in checkpoints
    }
    unpinned = {
        name: value
        for name, value in vars(constants).items()
        if name.startswith("PROGRESS_") and value not in pinned
    }
    assert not unpinned, (
        f"PROGRESS_* constants outside the monotonicity invariant: "
        f"{unpinned}. Add their node to _NODE_CHECKPOINTS (or exempt it "
        "by name) so the first-pass walk covers them."
    )


_ADVANCED_KNOBS = frozenset(
    {
        "supervisor_model_name",
        "tournament_pairs",
        "elo_k_factor",
        "literature_review_papers_count",
        "enable_cache",
        "cache_dir",
        "tools_config",
        "disable_tools",
        "budget",
    }
)


def _make_gen(**overrides: Any) -> HypothesisGenerator:
    """Build a small, fast generator; overrides tweak individual knobs.

    Overrides may name any constructor knob flatly; advanced knobs are
    routed into ``GeneratorOptions`` for the caller.
    """
    params: dict[str, Any] = {
        "model_name": "fake/model",
        "max_iterations": 1,
        "initial_hypotheses_count": 2,
        "evolution_max_count": 2,
    }
    options: dict[str, Any] = {"tournament_pairs": 2, "enable_cache": False}
    for key, value in overrides.items():
        (options if key in _ADVANCED_KNOBS else params)[key] = value
    return HypothesisGenerator(**params, options=GeneratorOptions(**options))


def _generations(
    final_state: WorkflowState,
) -> tuple[list[Hypothesis], list[Hypothesis]]:
    """Split the final pool into generation-0 parents and their children."""
    hyps = final_state["hypotheses"]
    parents = [h for h in hyps if h.generation == 0]
    children = [h for h in hyps if h.generation >= 1]
    return parents, children


def _assert_iteration_children(
    children: list[Hypothesis], parent_ids: set[str]
) -> None:
    """Each child is a fresh, reviewed EVOLUTION entrant of a real parent."""
    for child in children:
        assert child.origin is HypothesisOrigin.EVOLUTION
        assert child.parent_id in parent_ids
        assert child.generation == 1
        assert len(child.reviews) >= 1  # reviewed before ranking
        assert child.evolution_history


def _assert_top_ranked_verified(final_state: WorkflowState) -> None:
    """Deep verification probed the top hypothesis by Elo (top-k, not all)."""
    ranked = sorted(
        final_state["hypotheses"], key=lambda h: h.elo_rating, reverse=True
    )
    assert ranked[0].deep_verification_verdict
    assert ranked[0].deep_verification_probes


def _assert_meta_review_shape(final_state: WorkflowState) -> None:
    """Meta-review synthesis ran and produced the expected shape."""
    meta_review = final_state["meta_review"]
    assert meta_review["summary"]
    assert "common_strengths" in meta_review
    assert "strategic_recommendations" in meta_review


def _assert_terminal_overview(final_state: WorkflowState) -> None:
    """Research overview was synthesized as the terminal step."""
    overview = final_state["research_overview"]
    assert overview is not None
    assert overview["overview"]
    assert overview["nih_specific_aims"]


def _assert_execution_metrics(final_state: WorkflowState) -> None:
    """Execution metrics were populated across nodes, not just one."""
    metrics = final_state["metrics"]
    assert metrics.llm_calls > 0
    assert metrics.reviews_count >= 2
    assert metrics.tournaments_count >= 2
    assert metrics.evolutions_count == 2


async def _run_graph(
    gen: HypothesisGenerator, research_goal: str, **opts: Any
) -> WorkflowState:
    """Prepares the initial state and runs the real graph to completion.

    Args:
        gen: A configured (but not yet run) HypothesisGenerator.
        research_goal: The research question to generate hypotheses for.
        **opts: Extra ``generate_hypotheses``-style opts merged in;
            literature review is disabled unless overridden here.

    Returns:
        The final WorkflowState after the graph run completes.
    """
    initial_state = await gen.prepare_task_state(
        research_goal,
        opts={"enable_literature_review_node": False, **opts},
    )
    assert gen._graph is not None  # built by prepare_task_state
    final_state = await gen._graph.ainvoke(
        initial_state, config={"recursion_limit": 100}
    )
    return cast(WorkflowState, final_state)


async def test_single_iteration_pipeline_updates_cross_node_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A max_iterations=1 run touches every node with consistent state.

    Covers the full cycle: supervisor -> generate -> review -> ranking ->
    verification -> meta_review -> evolve -> review -> ranking ->
    verification -> proximity -> research_overview.
    """
    install_fake_llm(monkeypatch)
    gen = _make_gen()

    final_state = await _run_graph(gen, "Explain how protein X folds")

    # The pool grew: 2 generation-0 parents plus 2 appended evolution children.
    hypotheses = final_state["hypotheses"]
    parents, children = _generations(final_state)
    assert len(parents) == 2
    assert len(children) == 2
    assert len(hypotheses) == 4
    # Every hypothesis has distinct text.
    texts = [h.text for h in hypotheses]
    assert len(texts) == len(set(texts))

    # Reviews are incremental: each parent reviewed once; children reviewed
    # before ranking (EVO-COMPETE-001).
    assert all(len(p.reviews) == 1 for p in parents)
    _assert_iteration_children(children, {p.id for p in parents})

    # The tournament judged matchups and moved Elo off the initial rating.
    assert final_state["tournament_matchups"]
    assert any(h.elo_rating != INITIAL_ELO_RATING for h in hypotheses)
    assert final_state["evolution_details"]  # evolution left an audit trail
    _assert_top_ranked_verified(final_state)
    _assert_meta_review_shape(final_state)
    _assert_terminal_overview(final_state)
    _assert_execution_metrics(final_state)

    # One full iteration cycle completed (proximity increments once per pass).
    assert final_state["current_iteration"] == 1


async def test_evolve_path_appends_immutable_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evolution appends immutable children; parents stay and both compete.

    Generates 3 hypotheses, caps evolution at 2: the 3 parents remain in the
    pool unchanged and up to 2 evolution children are appended, each linking
    back to a parent with a fresh generation. The pool grows rather than
    shrinking (paper invariant SSR §4, §12).
    """
    install_fake_llm(monkeypatch)
    gen = _make_gen(initial_hypotheses_count=3, tournament_pairs=3)

    final_state = await _run_graph(gen, "Identify a synthetic-lethal target")

    hypotheses = final_state["hypotheses"]
    # The pool grew beyond the 3 originals: children were appended, not
    # substituted for their parents.
    assert len(hypotheses) > 3

    parents, children = _generations(final_state)
    assert len(parents) == 3  # every parent survived
    assert children, "evolution should append at least one child"

    parent_ids = {h.id for h in parents}
    for child in children:
        # Each child is a fresh, immutable entrant linked to a real parent.
        assert child.parent_id in parent_ids
        assert child.origin is HypothesisOrigin.EVOLUTION
        assert child.evolution_history
        assert child.text not in [p.text for p in parents]

    # Evolution details record the parent->child edges.
    assert final_state["evolution_details"]
    for detail in final_state["evolution_details"]:
        assert detail["parent_id"] in parent_ids
        assert detail["original"] != detail["evolved"]
        assert detail["rationale"]


async def test_adaptive_orchestration_schedules_generation_and_records_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Supervisor loop generates after the first tournament, with reasons.

    M2 acceptance: over multiple iterations the orchestrator schedules new
    Generation work after the first tournament (not only Evolution), every
    scheduled task and the final stop carry a recorded reason, and the run
    terminates with an explicit termination reason.
    """
    install_fake_llm(monkeypatch)
    gen = _make_gen(max_iterations=3)

    final_state = await _run_graph(gen, "Explain how protein X folds")

    history = final_state["task_history"]
    assert history, "the orchestrator should record scheduled tasks"
    # Every scheduled task carries a non-empty recorded reason.
    for record in history:
        assert record["reason"], record

    tasks = [r["task_type"] for r in history]
    # Both evolution and new generation happen across the run; the first work
    # cycle evolves the leaders and a later cycle generates new regions.
    assert "evolve" in tasks
    assert "generate" in tasks
    # Generation is scheduled after the first evolve (a later cycle), not only
    # in the initial pass.
    assert tasks.index("generate") > tasks.index("evolve")

    # The run terminates with an explicit, recorded reason.
    assert tasks[-1] == "terminate"
    assert history[-1]["termination_reason"]
    assert final_state["termination_reason"]


async def test_budget_exhaustion_terminates_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hard LLM-call budget stops the run with a budget termination reason.

    Proves the budget is a real termination predicate, not just
    max_iterations.
    """
    install_fake_llm(monkeypatch)
    gen = HypothesisGenerator(
        model_name="fake/model",
        max_iterations=50,
        # would run for many cycles without a budget
        initial_hypotheses_count=2,
        evolution_max_count=2,
        options=GeneratorOptions(
            tournament_pairs=2,
            enable_cache=False,
            budget={"max_llm_calls": 12},
        ),
    )

    final_state = await _run_graph(gen, "Explain how protein X folds")

    # The run stopped on the budget, well before 50 iterations.
    assert final_state["termination_reason"] == "budget"
    assert final_state["current_iteration"] < 50
    terminate_records = [
        r for r in final_state["task_history"] if r["task_type"] == "terminate"
    ]
    assert terminate_records
    assert terminate_records[-1]["termination_reason"] == "budget"


async def test_zero_iteration_pipeline_deep_verifies_and_skips_iterate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """max_iterations=0 still deep-verifies once but skips the iterate cycle.

    Deep verification runs unconditionally right after ranking, so even a
    zero-iteration run should leave every hypothesis probed and verdicted,
    while meta_review/evolve/proximity -- gated behind the iterate
    routing -- never run at all.
    """
    install_fake_llm(monkeypatch)
    gen = _make_gen(max_iterations=0)

    final_state = await _run_graph(
        gen, "Repurpose an existing kinase inhibitor"
    )

    hypotheses = final_state["hypotheses"]
    assert len(hypotheses) == 2

    # Deep verification ran once, deterministically ("holds" is the first
    # allowed value in DEEP_VERIFICATION_SCHEMA's "verdict" enum).
    assert all(h.deep_verification_verdict == "holds" for h in hypotheses)
    assert all(h.deep_verification_probes for h in hypotheses)

    # The iterate cycle (meta_review / evolve / proximity) never ran, so
    # these stay at their untouched initial-state values.
    assert final_state["meta_review"] == {}
    assert final_state["evolution_details"] == []
    assert final_state["current_iteration"] == 0

    # The workflow still terminates through research_overview.
    overview = final_state["research_overview"]
    assert overview is not None
    assert overview["overview"]


_PACKAGE = "co_scientist.llm"
_ROOT = pathlib.Path(llm.__file__).parent

# Lowest first. ``profile`` states what is known about each model and imports
# nothing else here, so admission and request shaping can both read it.
# ``telemetry`` sits between two ``request`` modules: it reads token counts
# off ``request.response`` while ``request.completion`` records into it, so
# that one edge is allowed upward.
_LAYERS = (
    "profile",
    "values",
    "admission",
    "structured",
    "telemetry",
    "request",
    "precall",
    "attempts",
    "tools",
    "call",
)
_ALLOWED_UPWARD = {("telemetry", "request.response")}


def _modules() -> dict[str, pathlib.Path]:
    """Maps each module's dotted name below the package to its file."""
    return {
        ".".join(path.relative_to(_ROOT).with_suffix("").parts): path
        for path in _ROOT.rglob("*.py")
        if path.name != "__init__.py"
    }


def _runtime_nodes(body: list[ast.stmt]) -> Iterator[ast.ImportFrom]:
    """The ``from`` imports that run at import time, skipping type-only ones."""
    for node in body:
        if isinstance(node, ast.If) and "TYPE_CHECKING" not in ast.dump(
            node.test
        ):
            yield from _runtime_nodes(node.body + node.orelse)
        elif isinstance(node, ast.ImportFrom):
            yield node


def _targets(node: ast.ImportFrom, modules: set[str]) -> set[str]:
    """The package modules one import names (``""`` is the package)."""
    module = node.module or ""
    if not module.startswith(_PACKAGE):
        return set()
    base = module.removeprefix(_PACKAGE).removeprefix(".")
    joined = {f"{base}.{a.name}" if base else a.name for a in node.names}
    return {j if j in modules else base for j in joined}


def _runtime_imports(path: pathlib.Path, modules: set[str]) -> set[str]:
    """The package modules this file imports when it is first loaded."""
    found: set[str] = set()
    for node in _runtime_nodes(ast.parse(path.read_text()).body):
        found |= _targets(node, modules)
    return found


def _layer(module: str) -> int:
    return _LAYERS.index(module.split(".")[0])


def test_no_module_imports_the_interface_it_implements() -> None:
    """Siblings import each other where the name is defined."""
    modules = _modules()
    for name, path in modules.items():
        assert "" not in _runtime_imports(path, set(modules)), name


def test_imports_only_point_downward() -> None:
    """A lower layer never reaches into a higher one."""
    modules = _modules()
    for name, path in modules.items():
        for imported in _runtime_imports(path, set(modules)) - {""}:
            if (name.split(".")[0], imported) in _ALLOWED_UPWARD:
                continue
            assert _layer(imported) <= _layer(name), f"{name} -> {imported}"


def test_module_level_imports_form_no_cycle() -> None:
    """No module is reachable from itself through runtime imports."""
    modules = _modules()
    graph = {
        name: _runtime_imports(path, set(modules)) - {""}
        for name, path in modules.items()
    }
    for name in graph:
        assert name not in _reachable(graph, name), name


def _reachable(graph: dict[str, set[str]], start: str) -> set[str]:
    """Every module reachable from ``start`` by one or more imports."""
    seen: set[str] = set()
    todo = list(graph.get(start, ()))
    while todo:
        module = todo.pop()
        if module not in seen:
            seen.add(module)
            todo.extend(graph.get(module, ()))
    return seen


def _declared_edges(literature_review: bool) -> set[tuple[str, str]]:
    """The fixed edges the declaration calls for in one flow shape."""
    absent = set() if literature_review else literature_review_nodes()
    edges: set[tuple[str, str]] = set()
    for node, route in WORKFLOW_ROUTES.items():
        if node in absent:
            continue
        if isinstance(route, LiteratureGated):
            edges.add((node, route.pick(literature_review)))
        elif isinstance(route, str):
            edges.add((node, route))
    return edges


def test_every_registered_node_declares_a_successor_and_only_those() -> None:
    """The declaration covers the registry exactly, and names real nodes."""
    assert set(WORKFLOW_ROUTES) == set(NODE_REGISTRY)
    named = set(TASK_ROUTES.values()) | literature_review_nodes()
    for route in WORKFLOW_ROUTES.values():
        if isinstance(route, str):
            named.add(route)
        elif isinstance(route, LiteratureGated):
            named.add(route.off)
    assert named <= set(NODE_REGISTRY)


@pytest.mark.parametrize("literature_review", [True, False])
def test_the_graph_is_wired_from_the_declaration(
    literature_review: bool,
) -> None:
    """The compiled edges are the declared ones: no extra, none missing."""
    graph = build_graph(literature_review)
    assert set(graph.edges) == _declared_edges(literature_review)
    resolver_nodes = {
        node for node, route in WORKFLOW_ROUTES.items() if callable(route)
    }
    assert set(graph.branches) == resolver_nodes | {START}


def test_the_review_phase_runs_in_the_published_order() -> None:
    """Supervisor to loop point, in the order the listings give.

    Deep verification sits between the safety screen and ranking
    (``03-reflection.md``: verified, *then* AddToTournament), so no idea is
    ranked before its core assumptions have been probed.
    """
    state = make_state(mcp_available=True)
    chain = ["supervisor"]
    while chain[-1] != "orchestrator":
        successor = next_task_type(chain[-1], state)
        assert successor is not None
        chain.append(successor)
    assert chain == [
        "supervisor",
        "literature_review",
        "generate",
        "reflection",
        "review",
        "comprehensive_reflection",
        "safety_screen",
        "deep_verification",
        "ranking",
        "orchestrator",
    ]


# --- Declared divergences, in the order workflow_topology lists them -------


def _gated(node: str) -> LiteratureGated:
    route = WORKFLOW_ROUTES[node]
    assert isinstance(route, LiteratureGated)
    return route


@pytest.mark.parametrize("node", ["supervisor", "generate"])
def test_the_graph_takes_its_flow_shape_from_how_it_was_built(
    node: str,
) -> None:
    """Divergence 1, graph half: ``mcp_available`` in the state is not read.

    The shape is fixed when the graph is compiled (the nodes it skips are not
    registered at all), so the state a run carries cannot re-route it.
    """
    for literature_review in (True, False):
        graph = build_graph(literature_review)
        for mcp_available in (True, False):
            state = make_state(mcp_available=mcp_available)
            assert graph_successor(graph, node, state) == _gated(node).pick(
                literature_review
            )


@pytest.mark.parametrize("node", ["supervisor", "generate"])
def test_the_durable_path_takes_its_flow_shape_from_committed_state(
    node: str,
) -> None:
    """Divergence 1, durable half: ``mcp_available`` is read at commit time."""
    for mcp_available in (True, False):
        state = make_state(mcp_available=mcp_available)
        assert next_task_type(node, state) == _gated(node).pick(mcp_available)


def test_the_gated_routes_skip_the_literature_nodes_when_the_flow_is_off() -> (
    None
):
    """Divergence 1, concretely: which edges the shape changes."""
    assert _declared_edges(True) - _declared_edges(False) == {
        ("supervisor", "literature_review"),
        ("literature_review", "generate"),
        ("generate", "reflection"),
        ("reflection", "review"),
    }
    assert _declared_edges(False) - _declared_edges(True) == {
        ("supervisor", "generate"),
        ("generate", "review"),
    }
    assert literature_review_nodes() == {"literature_review", "reflection"}


def test_a_missing_mcp_flag_is_the_simplified_flow_on_the_durable_path() -> (
    None
):
    """Divergence 1: the durable selector treats an absent key as off."""
    state = make_state()
    del state["mcp_available"]  # type: ignore[misc]
    assert next_task_type("supervisor", state) == "generate"
    assert next_task_type("generate", state) == "review"


@pytest.mark.parametrize("node", ["literature_review", "reflection"])
def test_the_durable_path_still_routes_the_nodes_the_simplified_graph_lacks(
    node: str,
) -> None:
    """Divergence 1: with the flow off the graph has no such node at all."""
    state = make_state(mcp_available=False)
    assert graph_successor(build_graph(False), node, state) == ABSENT
    assert next_task_type(node, state) == WORKFLOW_ROUTES[node]


@pytest.mark.parametrize("node", sorted(WORKFLOW_ROUTES))
def test_a_safety_halt_ends_the_durable_path_from_every_node(
    node: str,
) -> None:
    """Divergence 2: ``safety_blocked`` stops the run; the graph ignores it."""
    graph = build_graph(True)
    for state in decision_states():
        halted = make_state(**{**state, "safety_blocked": True})
        assert next_task_type(node, halted) is None
        assert graph_successor(graph, node, halted) == graph_successor(
            graph, node, state
        )


def test_the_entry_edge_exists_only_on_the_graph() -> None:
    """Divergence 3: the graph enters through START; the durable path does not.

    A resumed run re-enters at the orchestrator on the graph; the durable
    path has no entry node to resolve, so asking for one is an error.
    """
    graph = build_graph(True)
    assert START not in WORKFLOW_ROUTES
    assert graph_successor(graph, START, make_state()) == "supervisor"
    assert graph_successor(graph, START, make_state(resume=True)) == (
        "orchestrator"
    )
    with pytest.raises(ValueError, match="unsupported completed task node"):
        next_task_type(START, make_state())


def test_the_end_of_the_run_is_none_durable_and_end_on_the_graph() -> None:
    """Divergence 4: one terminal state, two encodings of it."""
    state = make_state(next_task=TaskType.TERMINATE.value)
    graph = build_graph(True)
    branch = next(iter(graph.branches["research_overview"].values()))
    assert next_task_type("research_overview", state) is None
    assert branch.path.invoke(state) == END
    assert graph_successor(graph, "research_overview", state) is None


def _evolve_with_meta_review_stacked_ahead() -> WorkflowState:
    """A decision the scheduler never produces: EVOLVE already runs it."""
    return make_state(
        next_task=TaskType.EVOLVE.value,
        supervisor_queue_actions=[
            {
                "action": "enqueue",
                "task_type": TaskType.META_REVIEW.value,
                "reason": "stacked",
            }
        ],
    )


def test_the_graph_path_map_rejects_what_the_durable_path_returns() -> None:
    """Divergence 5: only a state the scheduler never produces tells them apart.

    ``stack_companions`` never stacks meta-review ahead of EVOLVE, which
    already runs it; were it to, the resolver would name ``meta_review``
    itself. The graph's path map for that node excludes the self-edge, so
    LangGraph would refuse the value, while the durable path returns it
    unchecked.
    """
    state = _evolve_with_meta_review_stacked_ahead()
    graph = build_graph(True)
    branch = next(iter(graph.branches["meta_review"].values()))
    chosen = branch.path.invoke(state)
    assert chosen == "meta_review"
    assert branch.ends is not None
    assert chosen not in branch.ends
    assert next_task_type("meta_review", state) == "meta_review"
