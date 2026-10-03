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

# Node keys persist in tasks and checkpoints; renaming requires a data
# migration.
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
    workflow = StateGraph(WorkflowState)
    _add_workflow_nodes(workflow, enable_literature_review_node=True)
    _add_workflow_edges(workflow, enable_literature_review_node=True)
    compiled = workflow.compile()
    return set(compiled.get_graph().nodes) - {"__start__", "__end__"}


def test_registry_pins_the_frozen_durable_node_keys() -> None:
    assert set(agents.NODE_REGISTRY) == FROZEN_DURABLE_NODE_KEYS


def test_graph_registry_and_task_runtime_agree() -> None:
    registry_keys = set(agents.NODE_REGISTRY)
    assert _compiled_graph_node_keys() == registry_keys
    assert set(task_runtime.TASK_NODES) == registry_keys


def test_node_to_agent_is_projected_from_the_registry() -> None:
    assert set(agents.NODE_TO_AGENT) == set(agents.NODE_REGISTRY)
    for key, spec in agents.NODE_REGISTRY.items():
        assert agents.NODE_TO_AGENT[key] == spec.agent


def test_every_agent_owns_at_least_one_node() -> None:
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
    assert agents.NODE_REGISTRY["supervisor"].node is supervisor_node
    assert agents.NODE_REGISTRY["generate"].node is generate_node
    assert agents.NODE_REGISTRY["review"].node is review_node
    assert task_runtime.TASK_NODES["generate"] is generate_node


def test_agent_modules_reexport_the_real_node_callables() -> None:
    assert agents.supervisor.supervisor_node is supervisor_node
    assert agents.generation.generate_node is generate_node
    assert agents.reflection.review_node is review_node


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

    async def _call(*_: Any, **__: Any) -> dict[str, Any]:
        raise error

    return _call


def _overview_state(**overrides: Any) -> Any:
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
    monkeypatch.setattr(ro, "call_llm_json", _raiser(error))
    state = _overview_state()

    out = await ro.research_overview_node(state)

    assert out["research_overview"] == {}
    assert state["degraded_nodes"] == ["research_overview"]


@pytest.mark.parametrize("error", _CONTROL_FLOW)
async def test_overview_reraises_the_worker_owned_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(ro, "call_llm_json", _raiser(error))

    with pytest.raises(type(error)):
        await ro.research_overview_node(_overview_state())


async def test_interim_overview_failure_is_not_a_degraded_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A periodic firing produces no report section to mark as degraded."""
    monkeypatch.setattr(ro, "call_llm_json", _raiser(_UPSTREAM))
    state = _overview_state(next_task=TaskType.SYNTHESIZE.value)

    out = await ro.research_overview_node(state)

    assert "interim_overview" not in out
    assert state.get("degraded_nodes", []) == []


def _reviewed_state() -> Any:
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
    monkeypatch.setattr(mr, "call_llm_json", _raiser(error))

    with pytest.raises(type(error)):
        await mr.meta_review_node(_reviewed_state())


def _pair_state() -> Any:
    return make_state(
        hypotheses=[make_hypothesis(text="A"), make_hypothesis(text="B")],
        research_goal="g",
        model_name="test/model",
    )


@pytest.mark.parametrize("error", [_TIMEOUT, _UPSTREAM])
async def test_proximity_degrades_on_an_unreachable_provider(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(px, "call_llm_json", _raiser(error))
    state = _pair_state()

    out = await px.proximity_node(state)

    assert len(out["hypotheses"]) == 2
    assert state["degraded_nodes"] == ["proximity_analysis"]


@pytest.mark.parametrize("error", _CONTROL_FLOW)
async def test_proximity_reraises_the_worker_owned_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(px, "call_llm_json", _raiser(error))

    with pytest.raises(type(error)):
        await px.proximity_node(_pair_state())


# The durable retry flag chooses retry or degradation; graphs leave it unset.
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
    """Use remaining durable retries before settling for a blank report
    section."""
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
    """Raising after the last retry would settle the run without its report."""
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
    monkeypatch.setattr(ro, "call_llm_json", _raiser(error))
    state = _overview_state(durable_retries_remain=retries_remain)

    with pytest.raises(type(error)):
        await ro.research_overview_node(state)

    assert state.get("degraded_nodes", []) == []


async def test_the_interim_firing_also_spends_its_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ro, "call_llm_json", _raiser(_UPSTREAM))
    state = _overview_state(
        next_task=TaskType.SYNTHESIZE.value, durable_retries_remain=True
    )

    with pytest.raises(APIError):
        await ro.research_overview_node(state)


def test_the_attempt_flag_never_rides_a_checkpoint() -> None:
    """The flag describes one attempt; checkpointing it would mislead later
    nodes."""
    envelope = serialize_workflow_state(
        _overview_state(durable_retries_remain=True), last_event_seq=0
    )

    assert "durable_retries_remain" not in envelope["state"]
    assert "durable_retries_remain" not in restore_workflow_state(envelope)


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

_EXEMPT_NODES = {
    "comprehensive_reflection",
    # Hardcoded 0-1 progress differs from the 0-100 constants and cannot join
    # this walk.
    "literature_review",
}


def _first_pass_order(mcp_available: bool) -> list[str]:
    state = make_state(mcp_available=mcp_available)

    def step(completed: str) -> str:
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
    node = step(node)
    order.append(node)

    state["next_task"] = "evolve"
    node = step("orchestrator")
    order.append(node)
    node = step(node)
    order.append(node)

    state["next_task"] = "terminate"
    order.append(step("orchestrator"))
    return order


def test_walk_is_the_first_pass_it_claims_to_cover() -> None:
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
    for name, checkpoints in _NODE_CHECKPOINTS.items():
        if len(checkpoints) < 2:
            continue
        start, complete = checkpoints[0], checkpoints[-1]
        assert start <= complete, name


def test_every_walked_node_is_covered_or_exempt() -> None:
    walked = set(_first_pass_order(True)) | set(_first_pass_order(False))
    uncovered = walked - set(_NODE_CHECKPOINTS) - _EXEMPT_NODES
    assert not uncovered, (
        f"walked nodes with no checkpoint coverage and no exemption: "
        f"{sorted(uncovered)}"
    )


def test_every_declared_progress_constant_is_pinned() -> None:
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
    hyps = final_state["hypotheses"]
    parents = [h for h in hyps if h.generation == 0]
    children = [h for h in hyps if h.generation >= 1]
    return parents, children


def _assert_iteration_children(
    children: list[Hypothesis], parent_ids: set[str]
) -> None:
    for child in children:
        assert child.origin is HypothesisOrigin.EVOLUTION
        assert child.parent_id in parent_ids
        assert child.generation == 1
        assert len(child.reviews) >= 1
        assert child.evolution_history


def _assert_top_ranked_verified(final_state: WorkflowState) -> None:
    ranked = sorted(
        final_state["hypotheses"], key=lambda h: h.elo_rating, reverse=True
    )
    assert ranked[0].deep_verification_verdict
    assert ranked[0].deep_verification_probes


def _assert_meta_review_shape(final_state: WorkflowState) -> None:
    meta_review = final_state["meta_review"]
    assert meta_review["summary"]
    assert "common_strengths" in meta_review
    assert "strategic_recommendations" in meta_review


def _assert_terminal_overview(final_state: WorkflowState) -> None:
    overview = final_state["research_overview"]
    assert overview is not None
    assert overview["overview"]
    assert overview["nih_specific_aims"]


def _assert_execution_metrics(final_state: WorkflowState) -> None:
    metrics = final_state["metrics"]
    assert metrics.llm_calls > 0
    assert metrics.reviews_count >= 2
    assert metrics.tournaments_count >= 2
    assert metrics.evolutions_count == 2


async def _run_graph(
    gen: HypothesisGenerator, research_goal: str, **opts: Any
) -> WorkflowState:
    initial_state = await gen.prepare_task_state(
        research_goal,
        opts={"enable_literature_review_node": False, **opts},
    )
    assert gen._graph is not None
    final_state = await gen._graph.ainvoke(
        initial_state, config={"recursion_limit": 100}
    )
    return cast(WorkflowState, final_state)


async def test_single_iteration_pipeline_updates_cross_node_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_llm(monkeypatch)
    gen = _make_gen()

    final_state = await _run_graph(gen, "Explain how protein X folds")

    hypotheses = final_state["hypotheses"]
    parents, children = _generations(final_state)
    assert len(parents) == 2
    assert len(children) == 2
    assert len(hypotheses) == 4
    texts = [h.text for h in hypotheses]
    assert len(texts) == len(set(texts))

    assert all(len(p.reviews) == 1 for p in parents)
    _assert_iteration_children(children, {p.id for p in parents})

    assert final_state["tournament_matchups"]
    assert any(h.elo_rating != INITIAL_ELO_RATING for h in hypotheses)
    assert final_state["evolution_details"]
    _assert_top_ranked_verified(final_state)
    _assert_meta_review_shape(final_state)
    _assert_terminal_overview(final_state)
    _assert_execution_metrics(final_state)

    assert final_state["current_iteration"] == 1


async def test_evolve_path_appends_immutable_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_llm(monkeypatch)
    gen = _make_gen(initial_hypotheses_count=3, tournament_pairs=3)

    final_state = await _run_graph(gen, "Identify a synthetic-lethal target")

    hypotheses = final_state["hypotheses"]
    assert len(hypotheses) > 3

    parents, children = _generations(final_state)
    assert len(parents) == 3
    assert children, "evolution should append at least one child"

    parent_ids = {h.id for h in parents}
    for child in children:
        assert child.parent_id in parent_ids
        assert child.origin is HypothesisOrigin.EVOLUTION
        assert child.evolution_history
        assert child.text not in [p.text for p in parents]

    assert final_state["evolution_details"]
    for detail in final_state["evolution_details"]:
        assert detail["parent_id"] in parent_ids
        assert detail["original"] != detail["evolved"]
        assert detail["rationale"]


async def test_adaptive_orchestration_schedules_generation_and_records_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_llm(monkeypatch)
    gen = _make_gen(max_iterations=3)

    final_state = await _run_graph(gen, "Explain how protein X folds")

    history = final_state["task_history"]
    assert history, "the orchestrator should record scheduled tasks"
    for record in history:
        assert record["reason"], record

    tasks = [r["task_type"] for r in history]
    assert "evolve" in tasks
    assert "generate" in tasks
    assert tasks.index("generate") > tasks.index("evolve")

    assert tasks[-1] == "terminate"
    assert history[-1]["termination_reason"]
    assert final_state["termination_reason"]


async def test_budget_exhaustion_terminates_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_llm(monkeypatch)
    gen = HypothesisGenerator(
        model_name="fake/model",
        max_iterations=50,
        initial_hypotheses_count=2,
        evolution_max_count=2,
        options=GeneratorOptions(
            tournament_pairs=2,
            enable_cache=False,
            budget={"max_llm_calls": 12},
        ),
    )

    final_state = await _run_graph(gen, "Explain how protein X folds")

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
    install_fake_llm(monkeypatch)
    gen = _make_gen(max_iterations=0)

    final_state = await _run_graph(
        gen, "Repurpose an existing kinase inhibitor"
    )

    hypotheses = final_state["hypotheses"]
    assert len(hypotheses) == 2

    assert all(h.deep_verification_verdict == "holds" for h in hypotheses)
    assert all(h.deep_verification_probes for h in hypotheses)

    assert final_state["meta_review"] == {}
    assert final_state["evolution_details"] == []
    assert final_state["current_iteration"] == 0

    overview = final_state["research_overview"]
    assert overview is not None
    assert overview["overview"]


_PACKAGE = "co_scientist.llm"
_ROOT = pathlib.Path(llm.__file__).parent

# Telemetry reads request.response; request.completion records into telemetry.
# That request-layer edge is the explicit layering exception.
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
    return {
        ".".join(path.relative_to(_ROOT).with_suffix("").parts): path
        for path in _ROOT.rglob("*.py")
        if path.name != "__init__.py"
    }


def _runtime_nodes(body: list[ast.stmt]) -> Iterator[ast.ImportFrom]:
    for node in body:
        if isinstance(node, ast.If) and "TYPE_CHECKING" not in ast.dump(
            node.test
        ):
            yield from _runtime_nodes(node.body + node.orelse)
        elif isinstance(node, ast.ImportFrom):
            yield node


def _targets(node: ast.ImportFrom, modules: set[str]) -> set[str]:
    module = node.module or ""
    if not module.startswith(_PACKAGE):
        return set()
    base = module.removeprefix(_PACKAGE).removeprefix(".")
    joined = {f"{base}.{a.name}" if base else a.name for a in node.names}
    return {j if j in modules else base for j in joined}


def _runtime_imports(path: pathlib.Path, modules: set[str]) -> set[str]:
    found: set[str] = set()
    for node in _runtime_nodes(ast.parse(path.read_text()).body):
        found |= _targets(node, modules)
    return found


def _layer(module: str) -> int:
    return _LAYERS.index(module.split(".")[0])


def test_no_module_imports_the_interface_it_implements() -> None:
    modules = _modules()
    for name, path in modules.items():
        assert "" not in _runtime_imports(path, set(modules)), name


def test_imports_only_point_downward() -> None:
    modules = _modules()
    for name, path in modules.items():
        for imported in _runtime_imports(path, set(modules)) - {""}:
            if (name.split(".")[0], imported) in _ALLOWED_UPWARD:
                continue
            assert _layer(imported) <= _layer(name), f"{name} -> {imported}"


def test_module_level_imports_form_no_cycle() -> None:
    modules = _modules()
    graph = {
        name: _runtime_imports(path, set(modules)) - {""}
        for name, path in modules.items()
    }
    for name in graph:
        assert name not in _reachable(graph, name), name


def _reachable(graph: dict[str, set[str]], start: str) -> set[str]:
    seen: set[str] = set()
    todo = list(graph.get(start, ()))
    while todo:
        module = todo.pop()
        if module not in seen:
            seen.add(module)
            todo.extend(graph.get(module, ()))
    return seen


def _declared_edges(literature_review: bool) -> set[tuple[str, str]]:
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
    graph = build_graph(literature_review)
    assert set(graph.edges) == _declared_edges(literature_review)
    resolver_nodes = {
        node for node, route in WORKFLOW_ROUTES.items() if callable(route)
    }
    assert set(graph.branches) == resolver_nodes | {START}


def test_the_review_phase_runs_in_the_published_order() -> None:
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


def _gated(node: str) -> LiteratureGated:
    route = WORKFLOW_ROUTES[node]
    assert isinstance(route, LiteratureGated)
    return route


@pytest.mark.parametrize("node", ["supervisor", "generate"])
def test_the_graph_takes_its_flow_shape_from_how_it_was_built(
    node: str,
) -> None:
    """The compiled graph cannot change topology from later state flags."""
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
    for mcp_available in (True, False):
        state = make_state(mcp_available=mcp_available)
        assert next_task_type(node, state) == _gated(node).pick(mcp_available)


def test_the_gated_routes_skip_the_literature_nodes_when_the_flow_is_off() -> (
    None
):
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
    state = make_state()
    del state["mcp_available"]  # type: ignore[misc]
    assert next_task_type("supervisor", state) == "generate"
    assert next_task_type("generate", state) == "review"


@pytest.mark.parametrize("node", ["literature_review", "reflection"])
def test_the_durable_path_still_routes_the_nodes_the_simplified_graph_lacks(
    node: str,
) -> None:
    state = make_state(mcp_available=False)
    assert graph_successor(build_graph(False), node, state) == ABSENT
    assert next_task_type(node, state) == WORKFLOW_ROUTES[node]


@pytest.mark.parametrize("node", sorted(WORKFLOW_ROUTES))
def test_a_safety_halt_ends_the_durable_path_from_every_node(
    node: str,
) -> None:
    graph = build_graph(True)
    for state in decision_states():
        halted = make_state(**{**state, "safety_blocked": True})
        assert next_task_type(node, halted) is None
        assert graph_successor(graph, node, halted) == graph_successor(
            graph, node, state
        )


def test_the_entry_edge_exists_only_on_the_graph() -> None:
    graph = build_graph(True)
    assert START not in WORKFLOW_ROUTES
    assert graph_successor(graph, START, make_state()) == "supervisor"
    assert graph_successor(graph, START, make_state(resume=True)) == (
        "orchestrator"
    )
    with pytest.raises(ValueError, match="unsupported completed task node"):
        next_task_type(START, make_state())


def test_the_end_of_the_run_is_none_durable_and_end_on_the_graph() -> None:
    state = make_state(next_task=TaskType.TERMINATE.value)
    graph = build_graph(True)
    branch = next(iter(graph.branches["research_overview"].values()))
    assert next_task_type("research_overview", state) is None
    assert branch.path.invoke(state) == END
    assert graph_successor(graph, "research_overview", state) is None


def _evolve_with_meta_review_stacked_ahead() -> WorkflowState:
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
    """Only a scheduler-impossible state exposes the graph's rejected self-
    edge."""
    state = _evolve_with_meta_review_stacked_ahead()
    graph = build_graph(True)
    branch = next(iter(graph.branches["meta_review"].values()))
    chosen = branch.path.invoke(state)
    assert chosen == "meta_review"
    assert branch.ends is not None
    assert chosen not in branch.ends
    assert next_task_type("meta_review", state) == "meta_review"
