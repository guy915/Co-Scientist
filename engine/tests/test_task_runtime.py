from __future__ import annotations

import ast
import asyncio
import logging
import operator
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any

import pytest
from langgraph.channels import BinaryOperatorAggregate
from langgraph.graph import StateGraph
from typing_extensions import TypedDict

from co_scientist import tool_effects
from co_scientist.agents.generation.literature_review.enrichment import (
    _build_enrichment_canonical_params,
)
from co_scientist.agents.generation.literature_tools.draft import (
    _setup_tool_provider,
)
from co_scientist.agents.generation.literature_tools.validate import (
    _build_search_canonical_params,
)
from co_scientist.agents.reflection.reflection_helpers import (
    get_kg_tools_for_workflow,
)
from co_scientist.cache import LLMCache
from co_scientist.config.registry import ToolRegistry
from co_scientist.config.schema import ToolConfig
from co_scientist.evidence.search_query import _build_query_tool_params
from co_scientist.llm import CompletionSpec, call_llm, precall
from co_scientist.llm.tools.loop import _execute_tool_calls
from co_scientist.models import Hypothesis, MetricDeltas, create_metrics_update
from co_scientist.state import AppendHypotheses, WorkflowState
from co_scientist.task_runtime import (
    TASK_NODES,
    apply_task_update,
    channel_reducers,
    execute_task_node,
    next_task_type,
    plan_portfolio,
)
from co_scientist.tool_effects import (
    ToolEffect,
    batch_by_effects,
    is_barrier,
    parse_effects,
    resolve_tool_effects,
)
from co_scientist.workflow_topology import WORKFLOW_ROUTES
from tests._llm_fake import (
    make_completion,
    make_message,
    make_usage,
    patch_acompletion,
)
from tests._state import (
    ABSENT,
    build_graph,
    decision_states,
    graph_successor,
    make_state,
)


def test_apply_task_update_uses_graph_state_reducers() -> None:
    state = make_state(hypotheses=[Hypothesis(text="parent")])
    child = Hypothesis(text="child")
    merged = apply_task_update(
        state,
        {
            "hypotheses": AppendHypotheses([child]),
            "metrics": create_metrics_update(deltas=MetricDeltas(llm_calls=2)),
        },
    )
    assert [hypothesis.text for hypothesis in merged["hypotheses"]] == [
        "parent",
        "child",
    ]
    assert merged["metrics"].llm_calls == 2


def test_a_second_researcher_does_not_erase_the_first_one() -> None:
    """Durable reducers mirror state annotations; missing entries silently
    overwrite provenance."""
    state = make_state(research_ledgers=[{"goal": "from the review"}])

    merged = apply_task_update(
        state, {"research_ledgers": [{"goal": "from a hypothesis"}]}
    )

    assert merged["research_ledgers"] == [
        {"goal": "from the review"},
        {"goal": "from a hypothesis"},
    ]


@pytest.mark.parametrize("literature_review", [True, False])
@pytest.mark.parametrize("node", sorted(WORKFLOW_ROUTES))
def test_next_task_type_mirrors_graph_topology(
    node: str, literature_review: bool
) -> None:
    graph = build_graph(literature_review)
    for state in decision_states():
        state["mcp_available"] = literature_review
        expected = graph_successor(graph, node, state)
        if expected == ABSENT:
            continue
        assert next_task_type(node, state) == expected, (
            node,
            state.get("next_task"),
        )


async def test_execute_task_node_runs_only_named_specialist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def handler(state: Any) -> dict[str, Any]:
        calls.append("review")
        return {"current_iteration": 7}

    monkeypatch.setitem(TASK_NODES, "review", handler)
    committed, successor = await execute_task_node("review", make_state())
    assert calls == ["review"]
    assert committed["current_iteration"] == 7
    assert successor == "comprehensive_reflection"


async def test_execute_task_node_captures_llm_telemetry_by_phase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setattr(
        precall,
        "get_cache",
        lambda: LLMCache(cache_dir=str(tmp_path), enabled=True),
    )
    patch_acompletion(
        monkeypatch,
        [make_completion(make_message("ok"), usage=make_usage(100, 40, 5))],
    )

    async def handler(state: Any) -> dict[str, Any]:
        await call_llm(
            "a prompt", CompletionSpec(model_name="task-runtime-test-model")
        )
        return {"current_iteration": 1}

    monkeypatch.setitem(TASK_NODES, "review", handler)
    committed, _ = await execute_task_node("review", make_state())

    usage = committed["metrics"].model_usage
    assert set(usage) == {"review::task-runtime-test-model"}
    entry = usage["review::task-runtime-test-model"]
    assert entry["calls"] == 1
    assert entry["prompt_tokens"] == 100
    assert entry["completion_tokens"] == 40
    assert entry["reasoning_tokens"] == 5
    assert entry["cache_misses"] == 1
    assert entry["cache_hits"] == 0
    assert entry["latency_seconds"] >= 0
    assert entry["errors"] == {}


@pytest.mark.parametrize(
    ("start", "mcp", "expected"),
    [
        # Fan-out successors remain unknown until the dynamically sized
        # aggregate commits.
        ("generate", True, ["generate"]),
        ("ranking", False, ["ranking"]),
        ("generate", False, ["generate"]),
        ("reflection", False, ["reflection", "review"]),
        ("safety_screen", False, ["safety_screen", "deep_verification"]),
        ("orchestrator", False, ["orchestrator"]),
        ("proximity", False, ["proximity", "orchestrator"]),
        ("evolve", False, ["evolve", "review"]),
        ("meta_review", False, ["meta_review"]),
        ("research_overview", False, ["research_overview"]),
    ],
)
def test_plan_portfolio_walks_the_deterministic_tail(
    start: str, mcp: bool, expected: list[str]
) -> None:
    state = make_state(mcp_available=mcp)
    assert plan_portfolio(start, state) == expected


@pytest.mark.parametrize(
    ("next_task", "expected"),
    [
        ("evolve", ["meta_review", "evolve", "review"]),
        ("meta_review", ["meta_review", "orchestrator"]),
    ],
)
def test_plan_portfolio_walks_meta_review_from_the_decision(
    next_task: str, expected: list[str]
) -> None:
    state = make_state(mcp_available=False)
    state["next_task"] = next_task
    assert plan_portfolio("meta_review", state) == expected


def test_plan_portfolio_walks_supervisor_when_mcp_is_known() -> None:
    state = make_state(mcp_available=True)
    assert plan_portfolio("supervisor", state) == [
        "supervisor",
        "literature_review",
        "generate",
    ]


def test_plan_portfolio_stops_at_an_unresolvable_resolver_route() -> None:
    """A missing resolver key is undecided, not a falsy branch that the
    portfolio can guess."""
    state = make_state()
    del state["mcp_available"]  # type: ignore[misc]
    assert plan_portfolio("supervisor", state) == ["supervisor"]


def test_plan_portfolio_never_calls_the_orchestrator_resolver() -> None:
    """next_task still holds the previous cycle until the orchestrator
    overwrites it."""
    state = make_state(mcp_available=False, next_task="evolve")
    assert plan_portfolio("proximity", state) == [
        "proximity",
        "orchestrator",
    ]


def test_durable_path_accumulates_tournament_matchups() -> None:
    """A missing durable reducer silently replaces earlier tournament
    history."""
    from co_scientist.task_runtime import apply_task_update

    state = make_state(
        hypotheses=[],
        tournament_matchups=[{"hypothesis_a_id": "a", "hypothesis_b_id": "b"}],
    )

    merged = apply_task_update(
        state,
        {
            "tournament_matchups": [
                {"hypothesis_a_id": "c", "hypothesis_b_id": "d"}
            ]
        },
    )

    assert [m["hypothesis_a_id"] for m in merged["tournament_matchups"]] == [
        "a",
        "c",
    ]


class _ToyState(TypedDict):
    log: Annotated[list[int], operator.add]
    total: Annotated[int, operator.add]
    last: int


def test_only_annotated_channels_get_a_reducer() -> None:
    assert set(channel_reducers(_ToyState)) == {"log", "total"}


def test_a_list_channel_reduces_onto_an_empty_list_when_absent() -> None:
    reduce_log = channel_reducers(_ToyState)["log"]

    assert reduce_log(None, [1]) == [1]
    assert reduce_log([1], [2]) == [1, 2]


def test_a_non_list_channel_receives_the_existing_value_unchanged() -> None:
    assert channel_reducers(_ToyState)["total"](2, 3) == 5


def test_workflow_state_reducers_match_the_compiled_graph() -> None:
    compiled = StateGraph(WorkflowState).channels
    reduced_by_langgraph = {
        name
        for name, channel in compiled.items()
        if isinstance(channel, BinaryOperatorAggregate)
    }

    assert set(channel_reducers(WorkflowState)) == reduced_by_langgraph


def _call(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"call_{name}", function=SimpleNamespace(name=name, arguments="{}")
    )


def test_parse_effects_combines_known_tokens() -> None:
    assert parse_effects(["read", "network"]) == (
        ToolEffect.READ | ToolEffect.NETWORK
    )


def test_parse_effects_ignores_case_and_surrounding_space() -> None:
    assert parse_effects([" Read ", "NETWORK"]) == (
        ToolEffect.READ | ToolEffect.NETWORK
    )


def test_parse_effects_treats_empty_declaration_as_barrier() -> None:
    # Unknown effects fail closed; dropping them would silently regain
    # concurrency.
    assert is_barrier(parse_effects([]))


def test_parse_effects_treats_unknown_token_as_barrier() -> None:
    assert is_barrier(parse_effects(["read", "exec"]))


def test_is_barrier_covers_write_append_and_process() -> None:
    assert is_barrier(ToolEffect.WRITE)
    assert is_barrier(ToolEffect.APPEND)
    assert is_barrier(ToolEffect.PROCESS)


def test_remote_reads_are_not_barriers() -> None:
    assert not is_barrier(ToolEffect.READ | ToolEffect.NETWORK)


def test_resolve_reads_declared_effects_from_the_registry() -> None:
    from co_scientist.config.registry import get_tool_registry

    tools = get_tool_registry().get_enabled_tools()
    mcp_names = [tool.mcp_tool_name for tool in tools.values()]
    assert mcp_names, "expected the shipped config to declare tools"
    assert not any(is_barrier(resolve_tool_effects(n)) for n in mcp_names)


def test_resolve_treats_an_unregistered_tool_as_a_barrier() -> None:
    assert is_barrier(resolve_tool_effects("no_such_tool_anywhere"))


def test_resolve_treats_a_broken_registry_as_a_barrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import co_scientist.config.registry as registry

    def _boom() -> Any:
        raise RuntimeError("config unreadable")

    monkeypatch.setattr(registry, "get_tool_registry", _boom)
    assert is_barrier(resolve_tool_effects("pubmed_search"))


def _patch_effects(
    monkeypatch: pytest.MonkeyPatch, mapping: dict[str, list[str]]
) -> None:
    monkeypatch.setattr(
        tool_effects,
        "resolve_tool_effects",
        lambda name: parse_effects(mapping.get(name, [])),
    )


def test_batch_groups_all_reads_into_one_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_effects(monkeypatch, {"a": ["read"], "b": ["read"]})
    batches = batch_by_effects([_call("a"), _call("b")])
    assert len(batches) == 1
    assert len(batches[0]) == 2


def test_batch_isolates_a_barrier_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_effects(
        monkeypatch, {"r1": ["read"], "w": ["process"], "r2": ["read"]}
    )
    batches = batch_by_effects([_call("r1"), _call("w"), _call("r2")])
    assert [[c.function.name for c in b] for b in batches] == [
        ["r1"],
        ["w"],
        ["r2"],
    ]


def test_batch_preserves_order_and_loses_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_effects(
        monkeypatch,
        {"a": ["read"], "b": ["read"], "w": ["write"], "c": ["read"]},
    )
    names = ["a", "b", "w", "c"]
    batches = batch_by_effects([_call(n) for n in names])
    flattened = [c.function.name for batch in batches for c in batch]
    assert flattened == names


def test_batch_isolates_an_undeclared_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_effects(monkeypatch, {"r1": ["read"], "r2": ["read"]})
    batches = batch_by_effects([_call("r1"), _call("mystery"), _call("r2")])
    assert len(batches) == 3


@pytest.mark.asyncio
async def test_barrier_tool_never_overlaps_a_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_effects(
        monkeypatch,
        {"read_a": ["read"], "spawn": ["process"], "read_b": ["read"]},
    )
    in_flight = 0
    overlapped_with_barrier = False

    async def executor(tool_call: Any) -> dict[str, Any]:
        nonlocal in_flight, overlapped_with_barrier
        name = tool_call.function.name
        in_flight += 1
        if name == "spawn" and in_flight > 1:
            overlapped_with_barrier = True
        # Yield so a genuinely concurrent sibling can be observed.
        await asyncio.sleep(0)
        in_flight -= 1
        return {"role": "tool", "content": name}

    results = await _execute_tool_calls(
        [_call("read_a"), _call("spawn"), _call("read_b")], executor
    )

    assert not overlapped_with_barrier
    assert [r["content"] for r in results] == ["read_a", "spawn", "read_b"]


@pytest.mark.asyncio
async def test_reads_still_run_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_effects(monkeypatch, {"a": ["read"], "b": ["read"]})
    peak = 0
    in_flight = 0

    async def executor(tool_call: Any) -> dict[str, Any]:
        nonlocal peak, in_flight
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0)
        in_flight -= 1
        return {"role": "tool", "content": tool_call.function.name}

    await _execute_tool_calls([_call("a"), _call("b")], executor)
    assert peak == 2


def test_every_declared_tool_declares_its_effects() -> None:
    """Fail-closed undeclared effects serialize calls; shipped declarations
    must avoid that slow default."""
    from co_scientist.config.registry import get_tool_registry

    serialized = [
        tool_id
        for tool_id, tool in get_tool_registry().get_enabled_tools().items()
        if is_barrier(parse_effects(tool.effects))
    ]
    assert serialized == []


# Parse the sibling MCP package: its separate dependencies are absent in this
# environment.
_MCP_SERVER_ROOT = Path(__file__).resolve().parents[1] / "mcp_server"


def _accepted_arguments(root: Path) -> dict[str, set[str]]:
    accepted: dict[str, set[str]] = {}
    for path in sorted(root.rglob("*.py")):
        if "tests" in path.parts:
            continue
        module = ast.parse(path.read_text(encoding="utf-8"))
        for name, params in _public_functions(module):
            accepted.setdefault(name, params)
    return accepted


def _public_functions(module: ast.Module) -> list[tuple[str, set[str]]]:
    functions = []
    for node in ast.walk(module):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        if not node.name.startswith("_"):
            functions.append((node.name, _parameter_names(node)))
    return functions


def _parameter_names(node: ast.AsyncFunctionDef | ast.FunctionDef) -> set[str]:
    return {arg.arg for arg in (*node.args.args, *node.args.kwonlyargs)}


@pytest.fixture(scope="module")
def accepted() -> dict[str, set[str]]:
    return _accepted_arguments(_MCP_SERVER_ROOT)


@pytest.fixture(scope="module")
def registry() -> ToolRegistry:
    return ToolRegistry()


def _assert_callable(
    tool_config: ToolConfig,
    params: dict[str, object],
    accepted: dict[str, set[str]],
) -> None:
    tool_name = tool_config.mcp_tool_name
    assert tool_name in accepted, f"{tool_name} is not defined by the server"
    unexpected = sorted(set(params) - accepted[tool_name])
    assert not unexpected, (
        f"{tool_name} would be called with {unexpected}, which its signature"
        f" does not accept; fix the parameter_mapping in tools.yaml"
    )


def _sources(registry: ToolRegistry) -> list[ToolConfig]:
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None
    configs = [
        registry.get_tool(source.tool)
        for source in workflow.get_enabled_search_sources()
    ]
    return [config for config in configs if config is not None]


def test_literature_search_sources_accept_their_query_params(
    registry: ToolRegistry, accepted: dict[str, set[str]]
) -> None:
    configs = _sources(registry)
    assert configs, "the default config must configure search sources"
    for tool_config in configs:
        params = _build_query_tool_params(
            "resistance reversal", "research_1", "run-1", 3, tool_config
        )
        _assert_callable(tool_config, params, accepted)


def test_validation_search_tools_accept_their_query_params(
    registry: ToolRegistry, accepted: dict[str, set[str]]
) -> None:
    tool_ids = registry.get_tools_for_workflow("validation")
    assert tool_ids, "the default config must configure validation tools"
    for tool_id in tool_ids:
        tool_config = registry.get_tool(tool_id)
        assert tool_config is not None
        if tool_config.category not in ("search", "search_with_content"):
            continue
        canonical = _build_search_canonical_params(
            "resistance reversal", 3, "research_1", "run-1"
        )
        _assert_callable(
            tool_config, tool_config.map_parameters(canonical), accepted
        )


def test_context_enrichment_tools_accept_their_entity_params(
    registry: ToolRegistry, accepted: dict[str, set[str]]
) -> None:
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None
    assert workflow.context_enrichment_tools
    for tool_id in workflow.context_enrichment_tools:
        tool_config = registry.get_tool(tool_id)
        assert tool_config is not None
        canonical = _build_enrichment_canonical_params("MCR-1")
        _assert_callable(
            tool_config, tool_config.map_parameters(canonical), accepted
        )


# Reflection sends INDRA arguments directly; source-type selection must exclude
# literature tools.
_KG_ENTITY_ARGUMENTS = {"agent", "limit", "evidence_limit"}


def test_reflection_kg_tools_accept_entity_arguments(
    registry: ToolRegistry, accepted: dict[str, set[str]]
) -> None:
    for tool_name in get_kg_tools_for_workflow(registry, "reflection"):
        assert tool_name in accepted, f"{tool_name} is not defined"
        unexpected = sorted(_KG_ENTITY_ARGUMENTS - accepted[tool_name])
        assert not unexpected, (
            f"{tool_name} would be queried with {unexpected}, which its"
            f" signature does not accept; it is not a knowledge-graph tool"
        )


def test_indra_example_config_selects_its_knowledge_graph_tool(
    accepted: dict[str, set[str]],
) -> None:
    example = (
        Path(__file__).resolve().parents[1]
        / "src/co_scientist/config/examples/indra_hfpef.yaml"
    )
    registry = ToolRegistry(config_path=str(example), skip_user_config=True)
    kg_tools = get_kg_tools_for_workflow(registry, "reflection")
    assert kg_tools, "the INDRA example must reach a knowledge-graph tool"
    for tool_name in kg_tools:
        assert accepted[tool_name] >= _KG_ENTITY_ARGUMENTS


def test_opencitations_is_exposed_only_through_draft_read_tools(
    registry: ToolRegistry,
) -> None:
    tool_id = "opencitations_citation_edges"
    tool_config = registry.get_tool(tool_id)
    assert tool_config is not None
    assert tool_config.mcp_tool_name == "get_opencitations_citation_edges"
    assert tool_config.category == "read"

    draft = registry.get_workflow("draft_generation")
    assert draft is not None
    assert tool_id in draft.read_tools
    assert tool_id in registry.get_tools_for_workflow("draft_generation")
    for workflow_name in ("literature_review", "validation", "reflection"):
        assert tool_id not in registry.get_tools_for_workflow(workflow_name)

    class DraftMCPClient:
        def get_tools(
            self, whitelist: list[str] | None = None
        ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
            names = registry.get_mcp_tool_names(
                registry.get_tools_for_workflow("draft_generation")
            )
            selected = (
                names
                if whitelist is None
                else [name for name in names if name in whitelist]
            )
            return (
                {name: object() for name in selected},
                [
                    {"type": "function", "function": {"name": name}}
                    for name in selected
                ],
            )

    _, model_tools, _ = _setup_tool_provider(
        DraftMCPClient(),
        registry,
        "draft_generation",
        "draft-test",
        logging.getLogger(__name__),
    )
    assert "get_opencitations_citation_edges" in {
        tool["function"]["name"] for tool in model_tools
    }
