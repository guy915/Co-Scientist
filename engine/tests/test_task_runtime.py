from __future__ import annotations

import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

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
    batch_by_effects,
    is_barrier,
    parse_effects,
    resolve_tool_effects,
)
from tests._llm_fake import (
    make_completion,
    make_message,
    make_tool_call,
    make_usage,
    patch_acompletion,
)
from tests._state import (
    decision_states,
    make_state,
)


def test_apply_task_update_uses_graph_state_reducers() -> None:
    """Durable reducers mirror state annotations; a missing entry silently
    overwrites provenance and tournament history."""
    state = make_state(
        hypotheses=[Hypothesis(text="parent")],
        research_ledgers=[{"goal": "from the review"}],
        tournament_matchups=[{"hypothesis_a_id": "a", "hypothesis_b_id": "b"}],
    )
    child = Hypothesis(text="child")
    merged = apply_task_update(
        state,
        {
            "hypotheses": AppendHypotheses([child]),
            "metrics": create_metrics_update(deltas=MetricDeltas(llm_calls=2)),
            "research_ledgers": [{"goal": "from a hypothesis"}],
            "tournament_matchups": [
                {"hypothesis_a_id": "c", "hypothesis_b_id": "d"}
            ],
        },
    )
    assert merged["research_ledgers"] == [
        {"goal": "from the review"},
        {"goal": "from a hypothesis"},
    ]
    assert [m["hypothesis_a_id"] for m in merged["tournament_matchups"]] == [
        "a",
        "c",
    ]
    assert [hypothesis.text for hypothesis in merged["hypotheses"]] == [
        "parent",
        "child",
    ]
    assert merged["metrics"].llm_calls == 2


@pytest.mark.parametrize("mcp_available", [True, False])
@pytest.mark.parametrize(
    ("node", "on", "off"),
    [
        ("supervisor", "literature_review", "generate"),
        ("literature_review", "generate", "generate"),
        ("generate", "reflection", "review"),
        ("reflection", "review", "review"),
        ("review", "comprehensive_reflection", "comprehensive_reflection"),
        ("comprehensive_reflection", "safety_screen", "safety_screen"),
        ("safety_screen", "deep_verification", "deep_verification"),
        ("deep_verification", "ranking", "ranking"),
        ("ranking", "orchestrator", "orchestrator"),
        ("proximity", "orchestrator", "orchestrator"),
        ("evolve", "review", "review"),
    ],
)
def test_committed_nodes_follow_the_durable_scientific_chain(
    node: str, on: str, off: str, mcp_available: bool
) -> None:
    for state in decision_states():
        state["mcp_available"] = mcp_available
        assert next_task_type(node, state) == (on if mcp_available else off)


@pytest.mark.parametrize(
    ("decision", "orchestrator", "meta_review", "overview"),
    [
        (None, "research_overview", "research_overview", None),
        ("not_a_task", "research_overview", "research_overview", None),
        ("generate", "generate", "generate", None),
        ("reflect", "review", "review", None),
        ("rank", "safety_screen", "safety_screen", None),
        ("evolve", "meta_review", "evolve", None),
        ("proximity", "proximity", "proximity", None),
        ("meta_review", "meta_review", "orchestrator", None),
        (
            "synthesize",
            "research_overview",
            "research_overview",
            "orchestrator",
        ),
        ("terminate", "research_overview", "research_overview", None),
    ],
)
def test_decision_routes_preserve_prefix_periodic_and_terminal_behavior(
    decision: str | None,
    orchestrator: str,
    meta_review: str,
    overview: str | None,
) -> None:
    state = make_state(next_task=decision)
    assert next_task_type("orchestrator", state) == orchestrator
    assert next_task_type("meta_review", state) == meta_review
    assert next_task_type("research_overview", state) == overview


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
        ("supervisor", True, ["supervisor", "literature_review", "generate"]),
        ("research_overview", False, ["research_overview"]),
    ],
)
def test_plan_portfolio_walks_the_deterministic_tail(
    start: str, mcp: bool, expected: list[str]
) -> None:
    state = make_state(mcp_available=mcp)
    assert plan_portfolio(start, state) == expected


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


def test_workflow_state_reducers_cover_every_accumulating_channel() -> None:
    assert set(channel_reducers(WorkflowState)) == {
        "hypotheses",
        "tournament_matchups",
        "metrics",
        "messages",
        "research_ledgers",
    }


def _call(name: str) -> SimpleNamespace:
    return make_tool_call(f"call_{name}", name, "{}")


def test_resolve_reads_declared_effects_from_the_registry() -> None:
    from co_scientist.config.registry import get_tool_registry

    tools = get_tool_registry().get_enabled_tools()
    mcp_names = [tool.mcp_tool_name for tool in tools.values()]
    assert mcp_names, "expected the shipped config to declare tools"
    assert not any(is_barrier(resolve_tool_effects(n)) for n in mcp_names)


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


@pytest.mark.parametrize(
    ("declared", "is_a_barrier"),
    [
        (["read", "network"], False),
        ([" Read ", "NETWORK"], False),
        # Unknown or missing effects fail closed; dropping them would silently
        # regain concurrency.
        ([], True),
        (["read", "exec"], True),
        (["write"], True),
        (["append"], True),
        (["process"], True),
    ],
)
def test_declared_effects_decide_whether_a_tool_is_a_barrier(
    declared: list[str], is_a_barrier: bool
) -> None:
    assert is_barrier(parse_effects(declared)) is is_a_barrier


def test_batching_isolates_barriers_and_undeclared_tools_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_effects(
        monkeypatch,
        {"a": ["read"], "b": ["read"], "w": ["write"], "c": ["read"]},
    )
    batches = batch_by_effects(
        [_call(n) for n in ("a", "b", "w", "c", "mystery")]
    )
    assert [[call.function.name for call in b] for b in batches] == [
        ["a", "b"],
        ["w"],
        ["c"],
        ["mystery"],
    ]
