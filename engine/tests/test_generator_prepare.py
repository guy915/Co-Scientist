"""Tests for ``HypothesisGenerator._prepare_generation`` and MCP probing.

Split from ``test_generator.py``: the async initial-state assembly and the
MCP-availability behavior, with the two MCP probes stubbed to run offline.
"""

from typing import Any

import pytest

from co_scientist import mcp_client
from co_scientist.generator import (
    GeneratorOptions,
    HypothesisGenerator,
)


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
    monkeypatch.setattr(mcp_client, "check_literature_source_available", fake)


async def test_prepare_generation_populates_core_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Initial state carries the configured model names and counts."""
    _stub_mcp(monkeypatch, available=False)
    gen = HypothesisGenerator(
        model_name="m",
        max_iterations=2,
        initial_hypotheses_count=7,
        evolution_max_count=4,
        options=GeneratorOptions(
            supervisor_model_name="sup",
        ),
    )
    state = await gen._prepare_generation("Cure X")
    assert state["research_goal"] == "Cure X"
    assert state["model_name"] == "m"
    assert state["supervisor_model_name"] == "sup"
    assert state["max_iterations"] == 2
    assert state["initial_hypotheses_count"] == 7
    assert state["evolution_max_count"] == 4
    assert state["hypotheses"] == []
    assert state["current_iteration"] == 0
    registry = state["tool_registry"]
    assert registry is gen._tool_registry
    assert registry is not None
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None and workflow.is_multi_source()


async def test_prepare_generation_generates_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run_id is auto-generated and threaded into the state when absent."""
    _stub_mcp(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen._prepare_generation("goal")
    assert state["run_id"]


async def test_prepare_generation_honors_explicit_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller-supplied run_id is used verbatim."""
    _stub_mcp(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen._prepare_generation("goal", run_id="fixed-id")
    assert state["run_id"] == "fixed-id"


async def test_prepare_generation_passes_through_opts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    state = await gen._prepare_generation("goal", opts=opts)
    assert state["preferences"] == "pref-X"
    assert state["attributes"] == ["attr-Y"]
    assert state["constraints"] == ["cons-Z"]
    assert state["starting_hypotheses"] == ["h1"]
    assert state["literature"] == ["lit1"]


async def test_prepare_generation_opt_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Omitted optional fields default to None / empty / False."""
    _stub_mcp(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen._prepare_generation("goal")
    assert state["preferences"] is None
    assert state["attributes"] is None
    assert state["constraints"] is None
    assert state["starting_hypotheses"] is None
    assert state["literature"] is None
    assert state["enable_tool_calling_generation"] is False
    assert state["dev_test_lit_tools_isolation"] is False


async def test_prepare_generation_dev_isolation_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dev lit-tools isolation flag is passed through to the state."""
    _stub_mcp(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen._prepare_generation(
        "goal", opts={"dev_test_lit_tools_isolation": True}
    )
    assert state["dev_test_lit_tools_isolation"] is True


# --- _prepare_generation: MCP detection & graph selection --------------------


async def test_mcp_available_enables_lit_review_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When MCP is available the auto-detected graph includes lit review."""
    _stub_mcp(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen._prepare_generation("goal")
    assert state["mcp_available"] is True
    assert state["pubmed_available"] is True
    assert gen._graph is not None
    assert "literature_review" in gen._graph.nodes


async def test_mcp_unavailable_uses_simplified_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without MCP, lit review is dropped and flags reflect unavailability."""
    _stub_mcp(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen._prepare_generation("goal")
    assert state["mcp_available"] is False
    assert gen._graph is not None
    assert "literature_review" not in gen._graph.nodes


async def test_mcp_availability_cached_per_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP probes run once; the cached result persists across calls."""
    calls = {"n": 0}

    async def counting(**_: Any) -> bool:
        calls["n"] += 1
        return True

    monkeypatch.setattr(mcp_client, "check_mcp_available", counting)
    monkeypatch.setattr(
        mcp_client, "check_literature_source_available", counting
    )

    gen = HypothesisGenerator()
    await gen._prepare_generation("goal")
    after_first = calls["n"]
    await gen._prepare_generation("goal again")
    # No additional probe calls on the second preparation.
    assert calls["n"] == after_first
    assert gen._mcp_available is True


async def test_explicit_disable_skips_mcp_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicitly disabling lit review avoids invoking the MCP probes."""

    async def explode(**_: Any) -> bool:
        raise AssertionError("MCP probe should not be called")

    monkeypatch.setattr(mcp_client, "check_mcp_available", explode)
    monkeypatch.setattr(
        mcp_client, "check_literature_source_available", explode
    )

    gen = HypothesisGenerator()
    state = await gen._prepare_generation(
        "goal", opts={"enable_literature_review_node": False}
    )
    assert state["mcp_available"] is False
    assert gen._graph is not None
    assert "literature_review" not in gen._graph.nodes


async def test_tool_calling_honored_when_mcp_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool-calling generation stays on when MCP + lit review are available."""
    _stub_mcp(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen._prepare_generation(
        "goal", opts={"enable_tool_calling_generation": True}
    )
    assert state["enable_tool_calling_generation"] is True


async def test_tool_calling_disabled_when_mcp_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool-calling generation is silently disabled when MCP is unavailable."""
    _stub_mcp(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen._prepare_generation(
        "goal", opts={"enable_tool_calling_generation": True}
    )
    assert state["enable_tool_calling_generation"] is False


async def test_tool_calling_with_lit_disabled_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    state = await gen._prepare_generation(
        "goal",
        opts={
            "enable_literature_review_node": False,
            "enable_tool_calling_generation": True,
        },
    )
    assert state["enable_tool_calling_generation"] is False
    assert state["mcp_available"] is False
