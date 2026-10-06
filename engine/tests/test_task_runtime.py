from __future__ import annotations

import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist import tool_effects
from co_scientist.agents.reflection.reflection_helpers import (
    get_kg_tools_for_workflow,
)
from co_scientist.cache import LLMCache
from co_scientist.config.registry import ToolRegistry
from co_scientist.llm import CompletionSpec, call_llm, precall
from co_scientist.llm.tools.loop import (
    _execute_logged_tool,
    _execute_tool_calls,
)
from co_scientist.state import WorkflowState
from co_scientist.task_runtime import (
    TASK_NODES,
    channel_reducers,
    execute_task_node,
    plan_portfolio,
)
from co_scientist.tool_effects import (
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
from tests._state import make_state


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


# Reflection sends INDRA arguments directly; source-type selection must exclude
# literature tools.
_KG_ENTITY_ARGUMENTS = {"agent", "limit", "evidence_limit"}


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


@pytest.mark.parametrize("outcome", ["returned", "failed", "cancelled"])
async def test_tool_diagnostics_preserve_outcome_without_arguments_or_output(
    caplog: pytest.LogCaptureFixture, outcome: str
) -> None:
    call = make_tool_call("call-id", "search_literature", "private request")
    calls: list[Any] = []

    async def execute(value: Any) -> dict[str, Any]:
        calls.append(value)
        if outcome == "failed":
            raise ValueError("private error")
        if outcome == "cancelled":
            raise asyncio.CancelledError()
        return {"role": "tool", "content": "private result"}

    with caplog.at_level(logging.INFO, logger="co_scientist.llm.tools.loop"):
        if outcome == "failed":
            with pytest.raises(ValueError):
                await _execute_logged_tool(call, execute)
        elif outcome == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                await _execute_logged_tool(call, execute)
        else:
            assert await _execute_logged_tool(call, execute) == {
                "role": "tool",
                "content": "private result",
            }
    assert calls == [call]
    assert "name=search_literature" in caplog.text
    assert (
        f"outcome={outcome}" in caplog.text
        and "duration_seconds=" in caplog.text
    )
    assert "private" not in caplog.text
