from __future__ import annotations

import ast
import itertools
import pathlib
from collections.abc import Iterator
from typing import Any

import pytest
from litellm.exceptions import APIError

import co_scientist.llm as llm
from co_scientist import agents, constants, task_runtime
from co_scientist.agents import NODE_REGISTRY
from co_scientist.agents.meta_review import meta_review as mr
from co_scientist.agents.meta_review import research_overview as ro
from co_scientist.agents.proximity import proximity as px
from co_scientist.checkpoint import (
    restore_workflow_state,
    serialize_workflow_state,
)
from co_scientist.exceptions import (
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
    LLMTimeoutError,
)
from co_scientist.scheduling import TaskType
from co_scientist.state import WorkflowState
from co_scientist.task_runtime import next_task_type
from co_scientist.workflow_topology import (
    TASK_ROUTES,
    WORKFLOW_ROUTES,
    LiteratureGated,
    literature_review_nodes,
)
from tests._state import (
    decision_states,
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


def test_registry_pins_the_frozen_durable_node_keys() -> None:
    assert set(agents.NODE_REGISTRY) == FROZEN_DURABLE_NODE_KEYS
    assert set(task_runtime.TASK_NODES) == FROZEN_DURABLE_NODE_KEYS


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


def _reviewed_state() -> Any:
    hypothesis = make_hypothesis(text="H")
    hypothesis.reviews = [make_review()]
    return make_state(
        hypotheses=[hypothesis],
        research_goal="g",
        supervisor_model_name="test/model",
    )


def _pair_state() -> Any:
    return make_state(
        hypotheses=[make_hypothesis(text="A"), make_hypothesis(text="B")],
        research_goal="g",
        model_name="test/model",
    )


# (module, node, state builder, name recorded in degraded_nodes)
_NODE_CASES = [
    pytest.param(
        ro,
        ro.research_overview_node,
        _overview_state,
        "research_overview",
        id="research_overview",
    ),
    pytest.param(
        mr,
        mr.meta_review_node,
        _reviewed_state,
        "meta_review",
        id="meta_review",
    ),
    pytest.param(
        px,
        px.proximity_node,
        _pair_state,
        "proximity_analysis",
        id="proximity",
    ),
]


@pytest.mark.parametrize(
    ("module", "node", "build_state", "degraded_name"), _NODE_CASES
)
@pytest.mark.parametrize("error", [_TIMEOUT, _UPSTREAM])
@pytest.mark.parametrize(
    "retries_remain", [None, False, True], ids=["graph", "last", "remain"]
)
async def test_provider_failure_degrades_only_on_the_last_attempt(
    monkeypatch: pytest.MonkeyPatch,
    module: Any,
    node: Any,
    build_state: Any,
    degraded_name: str,
    error: Exception,
    retries_remain: bool | None,
) -> None:
    """Use remaining durable retries before settling for a blank report
    section; raising after the last one would settle the run without it."""
    monkeypatch.setattr(module, "call_llm_json", _raiser(error))
    state = build_state()
    if retries_remain is not None:
        state["durable_retries_remain"] = retries_remain

    if retries_remain:
        with pytest.raises(type(error)):
            await node(state)
        assert state.get("degraded_nodes", []) == []
    else:
        await node(state)
        assert state["degraded_nodes"] == [degraded_name]


@pytest.mark.parametrize(("module", "node", "build_state", "_"), _NODE_CASES)
@pytest.mark.parametrize("error", _CONTROL_FLOW)
@pytest.mark.parametrize("retries_remain", [True, False])
async def test_worker_owned_errors_reraise_whatever_the_attempt(
    monkeypatch: pytest.MonkeyPatch,
    module: Any,
    node: Any,
    build_state: Any,
    _: str,
    error: Exception,
    retries_remain: bool,
) -> None:
    monkeypatch.setattr(module, "call_llm_json", _raiser(error))
    state = build_state()
    state["durable_retries_remain"] = retries_remain

    with pytest.raises(type(error)):
        await node(state)

    assert state.get("degraded_nodes", []) == []


async def test_a_degraded_meta_review_still_returns_an_empty_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mr, "call_llm_json", _raiser(_TIMEOUT))
    out = await mr.meta_review_node(_reviewed_state())
    assert out["meta_review"]["strategic_recommendations"] == []


async def test_an_interim_overview_failure_is_not_a_degraded_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A periodic firing produces no report section to mark as degraded."""
    monkeypatch.setattr(ro, "call_llm_json", _raiser(_UPSTREAM))
    state = _overview_state(next_task=TaskType.SYNTHESIZE.value)
    out = await ro.research_overview_node(state)
    assert "interim_overview" not in out
    assert state.get("degraded_nodes", []) == []


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
    return {
        (
            node,
            route.pick(literature_review)
            if isinstance(route, LiteratureGated)
            else route,
        )
        for node, route in WORKFLOW_ROUTES.items()
        if isinstance(route, (str, LiteratureGated))
    }


def test_every_registered_node_declares_a_successor_and_only_those() -> None:
    assert set(WORKFLOW_ROUTES) == set(NODE_REGISTRY)
    named = set(TASK_ROUTES.values()) | literature_review_nodes()
    for route in WORKFLOW_ROUTES.values():
        if isinstance(route, str):
            named.add(route)
        elif isinstance(route, LiteratureGated):
            named.add(route.off)
    assert named <= set(NODE_REGISTRY)


def _gated(node: str) -> LiteratureGated:
    route = WORKFLOW_ROUTES[node]
    assert isinstance(route, LiteratureGated)
    return route


def test_the_gated_routes_skip_the_literature_nodes_when_the_flow_is_off() -> (
    None
):
    assert _declared_edges(True) - _declared_edges(False) == {
        ("supervisor", "literature_review"),
        ("generate", "reflection"),
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


@pytest.mark.parametrize("node", sorted(WORKFLOW_ROUTES))
def test_a_safety_halt_ends_the_durable_path_from_every_node(
    node: str,
) -> None:
    for state in decision_states():
        halted = make_state(**{**state, "safety_blocked": True})
        assert next_task_type(node, halted) is None


def test_entry_marker_is_not_a_completed_durable_node() -> None:
    assert "__start__" not in WORKFLOW_ROUTES
    with pytest.raises(ValueError, match="unsupported completed task node"):
        next_task_type("__start__", make_state())


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


def test_meta_review_companion_routes_to_the_evolve_prefix() -> None:
    state = _evolve_with_meta_review_stacked_ahead()
    assert next_task_type("meta_review", state) == "meta_review"
