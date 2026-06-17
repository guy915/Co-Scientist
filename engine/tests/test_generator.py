"""Tests for the HypothesisGenerator public entry point.

These cover the parts that are deterministic without a full LLM run:
constructor configuration and env side effects, LangGraph compilation
(node sets for the literature-review and simplified flows), and the
``_prepare_generation`` helper that builds the initial ``WorkflowState``.
The two MCP-availability probes are stubbed so the helper runs offline.
"""

from typing import Any

import pytest

from langgraph.graph.state import CompiledStateGraph

from co_scientist import mcp_client
from co_scientist.constants import (
    DEFAULT_EVOLUTION_MAX_COUNT,
    DEFAULT_INITIAL_HYPOTHESES_COUNT,
    DEFAULT_MAX_ITERATIONS,
)
from co_scientist.generator import HypothesisGenerator

# Node set the graph compiles with literature review enabled. ``__start__`` is
# LangGraph's implicit entry node; ``END`` does not appear as a node key.
_LIT_NODES = {
    "__start__",
    "supervisor",
    "literature_review",
    "generate",
    "reflection",
    "review",
    "ranking",
    "meta_review",
    "evolve",
    "proximity",
}

# Node set for the simplified flow (no literature_review / reflection).
_SIMPLE_NODES = _LIT_NODES - {"literature_review", "reflection"}


def _stub_mcp(monkeypatch: pytest.MonkeyPatch, *, available: bool) -> None:
    """Patch both MCP-availability probes to a fixed boolean.

    ``_prepare_generation`` imports these names from ``co_scientist.mcp_client``
    at call time, so patching the source module suffices.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        available: Value both probes should return.
    """

    async def fake(**_: Any) -> bool:
        return available

    monkeypatch.setattr(mcp_client, "check_mcp_available", fake)
    monkeypatch.setattr(mcp_client, "check_pubmed_available_via_mcp", fake)


# --- Construction / configuration -------------------------------------------


def test_defaults_match_constants() -> None:
    """Unspecified counts fall back to the module-level defaults."""
    gen = HypothesisGenerator()
    assert gen.model_name == "gemini/gemini-2.5-flash"
    assert gen.max_iterations == DEFAULT_MAX_ITERATIONS
    assert gen.initial_hypotheses_count == DEFAULT_INITIAL_HYPOTHESES_COUNT
    assert gen.evolution_max_count == DEFAULT_EVOLUTION_MAX_COUNT


def test_config_overrides_are_stored() -> None:
    """Explicit constructor arguments are held verbatim on the instance."""
    gen = HypothesisGenerator(
        model_name="custom-model",
        max_iterations=3,
        initial_hypotheses_count=7,
        evolution_max_count=4,
    )
    assert gen.model_name == "custom-model"
    assert gen.max_iterations == 3
    assert gen.initial_hypotheses_count == 7
    assert gen.evolution_max_count == 4


def test_supervisor_model_defaults_to_model_name() -> None:
    """When no supervisor model is given it mirrors ``model_name``."""
    gen = HypothesisGenerator(model_name="only-model")
    assert gen.supervisor_model_name == "only-model"


def test_supervisor_model_override_is_independent() -> None:
    """An explicit supervisor model is kept distinct from ``model_name``."""
    gen = HypothesisGenerator(model_name="base", supervisor_model_name="sup")
    assert gen.model_name == "base"
    assert gen.supervisor_model_name == "sup"


def test_lazy_state_is_unset_before_first_run() -> None:
    """Graph and availability flags are lazily initialised (None) at first."""
    gen = HypothesisGenerator()
    assert gen._graph is None
    assert gen._mcp_available is None
    assert gen._pubmed_available is None
    assert gen._tool_registry is None


def test_enable_cache_true_sets_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``enable_cache=True`` exports the cache-enabled env var as 'true'."""
    monkeypatch.delenv("COSCIENTIST_CACHE_ENABLED", raising=False)
    HypothesisGenerator(enable_cache=True)
    import os  # pylint: disable=import-outside-toplevel

    assert os.environ["COSCIENTIST_CACHE_ENABLED"] == "true"


def test_enable_cache_false_sets_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``enable_cache=False`` exports the cache-enabled env var as 'false'."""
    monkeypatch.setenv("COSCIENTIST_CACHE_ENABLED", "true")
    HypothesisGenerator(enable_cache=False)
    import os  # pylint: disable=import-outside-toplevel

    assert os.environ["COSCIENTIST_CACHE_ENABLED"] == "false"


def test_cache_dir_sets_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``cache_dir`` exports the cache-directory env var."""
    monkeypatch.delenv("COSCIENTIST_CACHE_DIR", raising=False)
    HypothesisGenerator(cache_dir="/tmp/coscientist-test-cache")
    import os  # pylint: disable=import-outside-toplevel

    assert os.environ["COSCIENTIST_CACHE_DIR"] == "/tmp/coscientist-test-cache"


def test_cache_unset_leaves_env_untouched(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """With cache args left as None the constructor sets no cache env vars."""
    monkeypatch.delenv("COSCIENTIST_CACHE_ENABLED", raising=False)
    monkeypatch.delenv("COSCIENTIST_CACHE_DIR", raising=False)
    HypothesisGenerator()
    import os  # pylint: disable=import-outside-toplevel

    assert "COSCIENTIST_CACHE_ENABLED" not in os.environ
    assert "COSCIENTIST_CACHE_DIR" not in os.environ


# --- Graph compilation -------------------------------------------------------


def test_build_graph_with_literature_review_compiles() -> None:
    """The full flow compiles to a CompiledStateGraph with all nodes."""
    gen = HypothesisGenerator()
    graph = gen._build_graph(enable_literature_review_node=True)
    assert isinstance(graph, CompiledStateGraph)
    assert set(graph.nodes.keys()) == _LIT_NODES


def test_build_graph_without_literature_review_omits_nodes() -> None:
    """The simplified flow drops the literature_review and reflection nodes."""
    gen = HypothesisGenerator()
    graph = gen._build_graph(enable_literature_review_node=False)
    assert isinstance(graph, CompiledStateGraph)
    assert set(graph.nodes.keys()) == _SIMPLE_NODES
    assert "literature_review" not in graph.nodes
    assert "reflection" not in graph.nodes


# --- _prepare_generation: state building -------------------------------------


async def test_prepare_generation_populates_core_config(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Initial state carries the configured model names and counts."""
    _stub_mcp(monkeypatch, available=False)
    gen = HypothesisGenerator(
        model_name="m",
        supervisor_model_name="sup",
        max_iterations=2,
        initial_hypotheses_count=7,
        evolution_max_count=4,
    )
    state, _, _ = await gen._prepare_generation("Cure X")
    assert state["research_goal"] == "Cure X"
    assert state["model_name"] == "m"
    assert state["supervisor_model_name"] == "sup"
    assert state["max_iterations"] == 2
    assert state["initial_hypotheses_count"] == 7
    assert state["evolution_max_count"] == 4
    assert state["hypotheses"] == []
    assert state["current_iteration"] == 0
    assert state["tool_registry"] is None


async def test_prepare_generation_generates_run_id(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A run_id is auto-generated and threaded into the state when absent."""
    _stub_mcp(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state, _, run_id = await gen._prepare_generation("goal")
    assert run_id
    assert state["run_id"] == run_id


async def test_prepare_generation_honors_explicit_run_id(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A caller-supplied run_id is used verbatim."""
    _stub_mcp(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state, _, run_id = await gen._prepare_generation("goal", run_id="fixed-id")
    assert run_id == "fixed-id"
    assert state["run_id"] == "fixed-id"


async def test_prepare_generation_passes_through_opts(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Optional preferences/constraints and user inputs land in the state."""
    _stub_mcp(monkeypatch, available=False)
    gen = HypothesisGenerator()
    opts = {
        "preferences": "pref-X",
        "attributes": ["attr-Y"],
        "constraints": ["cons-Z"],
        "user_inputs": {
            "starting_hypotheses": ["h1"],
            "literature": ["lit1"],
        },
    }
    state, _, _ = await gen._prepare_generation("goal", opts=opts)
    assert state["preferences"] == "pref-X"
    assert state["attributes"] == ["attr-Y"]
    assert state["constraints"] == ["cons-Z"]
    assert state["starting_hypotheses"] == ["h1"]
    assert state["literature"] == ["lit1"]


async def test_prepare_generation_opt_defaults(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Omitted optional fields default to None / empty / False."""
    _stub_mcp(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state, _, _ = await gen._prepare_generation("goal")
    assert state["preferences"] is None
    assert state["attributes"] is None
    assert state["constraints"] is None
    assert state["starting_hypotheses"] is None
    assert state["literature"] is None
    assert state["enable_tool_calling_generation"] is False
    assert state["dev_test_lit_tools_isolation"] is False


async def test_prepare_generation_dev_isolation_flag(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The dev lit-tools isolation flag is passed through to the state."""
    _stub_mcp(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state, _, _ = await gen._prepare_generation(
        "goal", opts={"dev_test_lit_tools_isolation": True})
    assert state["dev_test_lit_tools_isolation"] is True


# --- _prepare_generation: MCP detection & graph selection --------------------


async def test_mcp_available_enables_lit_review_graph(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """When MCP is available the auto-detected graph includes lit review."""
    _stub_mcp(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state, _, _ = await gen._prepare_generation("goal")
    assert state["mcp_available"] is True
    assert state["pubmed_available"] is True
    assert gen._graph is not None
    assert "literature_review" in gen._graph.nodes


async def test_mcp_unavailable_uses_simplified_graph(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Without MCP, lit review is dropped and the flags reflect unavailability."""
    _stub_mcp(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state, _, _ = await gen._prepare_generation("goal")
    assert state["mcp_available"] is False
    assert gen._graph is not None
    assert "literature_review" not in gen._graph.nodes


async def test_mcp_availability_cached_per_instance(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP probes run once; the cached result persists across calls."""
    calls = {"n": 0}

    async def counting(**_: Any) -> bool:
        calls["n"] += 1
        return True

    monkeypatch.setattr(mcp_client, "check_mcp_available", counting)
    monkeypatch.setattr(mcp_client, "check_pubmed_available_via_mcp", counting)

    gen = HypothesisGenerator()
    await gen._prepare_generation("goal")
    after_first = calls["n"]
    await gen._prepare_generation("goal again")
    # No additional probe calls on the second preparation.
    assert calls["n"] == after_first
    assert gen._mcp_available is True


async def test_explicit_disable_skips_mcp_probe(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicitly disabling lit review avoids invoking the MCP probes."""

    async def explode(**_: Any) -> bool:
        raise AssertionError("MCP probe should not be called")

    monkeypatch.setattr(mcp_client, "check_mcp_available", explode)
    monkeypatch.setattr(mcp_client, "check_pubmed_available_via_mcp", explode)

    gen = HypothesisGenerator()
    state, _, _ = await gen._prepare_generation(
        "goal", opts={"enable_literature_review_node": False})
    assert state["mcp_available"] is False
    assert gen._graph is not None
    assert "literature_review" not in gen._graph.nodes


async def test_tool_calling_honored_when_mcp_available(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Tool-calling generation is kept on when MCP + lit review are available."""
    _stub_mcp(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state, _, _ = await gen._prepare_generation(
        "goal", opts={"enable_tool_calling_generation": True})
    assert state["enable_tool_calling_generation"] is True


async def test_tool_calling_disabled_when_mcp_unavailable(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Tool-calling generation is silently disabled when MCP is unavailable."""
    _stub_mcp(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state, _, _ = await gen._prepare_generation(
        "goal", opts={"enable_tool_calling_generation": True})
    assert state["enable_tool_calling_generation"] is False


async def test_tool_calling_with_lit_disabled_does_not_raise(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Tool calling + explicit lit-review-off degrades gracefully (no raise).

    Note: ``_prepare_generation`` documents a ValueError for this combination,
    but explicitly disabling the literature review forces ``mcp_available`` to
    False *before* the tool-calling validation runs, so the MCP-unavailable
    branch always fires first and the ValueError branch is never reached. This
    asserts the observed graceful-disable behavior rather than the documented
    raise.
    """
    _stub_mcp(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state, _, _ = await gen._prepare_generation(
        "goal",
        opts={
            "enable_literature_review_node": False,
            "enable_tool_calling_generation": True,
        },
    )
    assert state["enable_tool_calling_generation"] is False
    assert state["mcp_available"] is False
