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
from tests._mcp import stub_mcp_availability


async def test_prepare_generation_populates_core_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Initial state carries the configured model names and counts."""
    stub_mcp_availability(monkeypatch, available=False)
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
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen._prepare_generation("goal")
    assert state["run_id"]


async def test_prepare_generation_honors_explicit_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller-supplied run_id is used verbatim."""
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen._prepare_generation("goal", run_id="fixed-id")
    assert state["run_id"] == "fixed-id"


async def test_prepare_generation_passes_through_opts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optional preferences/constraints and user inputs land in the state."""
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    opts = {
        "preferences": "pref-X",
        "attributes": ["attr-Y"],
        "constraints": ["cons-Z"],
        # K5: the interview's lab constraints thread opts -> state -> prompts.
        "lab_constraints": ["zebrafish only"],
        "user_inputs": {
            "starting_hypotheses": ["h1"],
            "literature": ["lit1"],
        },
    }
    state = await gen._prepare_generation("goal", opts=opts)
    assert state["preferences"] == "pref-X"
    assert state["attributes"] == ["attr-Y"]
    assert state["constraints"] == ["cons-Z"]
    assert state["lab_constraints"] == ["zebrafish only"]
    assert state["starting_hypotheses"] == ["h1"]
    assert state["literature"] == ["lit1"]


async def test_prepare_generation_opt_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Omitted optional fields default to None / empty / False."""
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen._prepare_generation("goal")
    assert state["preferences"] is None
    assert state["attributes"] is None
    assert state["constraints"] is None
    assert state["lab_constraints"] is None
    assert state["starting_hypotheses"] is None
    assert state["literature"] is None
    assert state["enable_tool_calling_generation"] is False
    assert state["dev_test_lit_tools_isolation"] is False


async def test_prepare_generation_dev_isolation_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dev lit-tools isolation flag is passed through to the state."""
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen._prepare_generation(
        "goal", opts={"dev_test_lit_tools_isolation": True}
    )
    assert state["dev_test_lit_tools_isolation"] is True


async def test_prepare_generation_reads_dev_mode_env_into_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """COSCIENTIST_DEV_MODE is read here, at the boundary, and put in state.

    The literature review node consumes ``dev_mode`` from state, so this is
    the one place the env var is allowed to enter a run.
    """
    stub_mcp_availability(monkeypatch, available=False)
    monkeypatch.setenv("COSCIENTIST_DEV_MODE", "true")
    gen = HypothesisGenerator()
    state = await gen._prepare_generation("goal")
    assert state["dev_mode"] is True


async def test_prepare_generation_dev_mode_opt_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-run dev_mode opt beats the session-wide env var, either way."""
    stub_mcp_availability(monkeypatch, available=False)
    monkeypatch.setenv("COSCIENTIST_DEV_MODE", "true")
    gen = HypothesisGenerator()
    state = await gen._prepare_generation("goal", opts={"dev_mode": False})
    assert state["dev_mode"] is False

    monkeypatch.delenv("COSCIENTIST_DEV_MODE", raising=False)
    state = await gen._prepare_generation("goal", opts={"dev_mode": True})
    assert state["dev_mode"] is True


async def test_prepare_generation_dev_mode_defaults_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With neither an opt nor the env var, a run is not in dev mode."""
    stub_mcp_availability(monkeypatch, available=False)
    monkeypatch.delenv("COSCIENTIST_DEV_MODE", raising=False)
    gen = HypothesisGenerator()
    state = await gen._prepare_generation("goal")
    assert state["dev_mode"] is False


# --- _prepare_generation: MCP detection & graph selection --------------------


async def test_mcp_available_enables_lit_review_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When MCP is available the auto-detected graph includes lit review."""
    stub_mcp_availability(monkeypatch, available=True)
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
    stub_mcp_availability(monkeypatch, available=False)
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
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen._prepare_generation(
        "goal", opts={"enable_tool_calling_generation": True}
    )
    assert state["enable_tool_calling_generation"] is True


async def test_tool_calling_disabled_when_mcp_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool-calling generation is silently disabled when MCP is unavailable."""
    stub_mcp_availability(monkeypatch, available=False)
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
    stub_mcp_availability(monkeypatch, available=True)
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


# --- E11a: tool-calling generation is opt-in, even where tools exist ---


async def test_tool_calling_off_by_default_when_tools_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Available tools are not on their own a request for the agentic path.

    The draft agent spends one LLM round-trip per tool call and re-sends
    every prior result, so it costs roughly nine calls per hypothesis on
    prompts that grow past 12k tokens -- per hypothesis, per cycle. Live
    telemetry had it as the largest single line in an express run's token
    budget. Availability decides whether it *can* run; the caller decides
    whether it *should*, and the app opts in only for the deep tiers.
    """
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen._prepare_generation("goal")
    assert state["enable_tool_calling_generation"] is False


async def test_tool_calling_opt_in_survives_prepare_task_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The durable-task entry point carries an explicit opt-in through.

    ``prepare_task_state`` is the exact call the app's durable executor
    makes before enqueueing node tasks, so the flag it writes decides
    whether the generation fan-out allocates the tool-based strategy.
    """
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal", opts={"enable_tool_calling_generation": True}
    )
    assert state["enable_tool_calling_generation"] is True


async def test_tool_calling_explicit_opt_out_honored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit False opts out even when tools are available."""
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen._prepare_generation(
        "goal", opts={"enable_tool_calling_generation": False}
    )
    assert state["enable_tool_calling_generation"] is False


async def test_tool_calling_stays_off_by_default_without_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without MCP there are no literature tools, so the default is off."""
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen._prepare_generation("goal")
    assert state["enable_tool_calling_generation"] is False


async def test_tool_calling_forced_off_for_offline_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline runs keep the plain deterministic path even with MCP.

    The offline responder never emits tool calls, so a tool loop would
    "finish" on its first canned reply and fail parsing; the capability
    default must not admit that.
    """
    from co_scientist.offline_llm import DEFAULT_OFFLINE_MODEL

    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator(model_name=DEFAULT_OFFLINE_MODEL)
    state = await gen._prepare_generation("goal")
    assert state["enable_tool_calling_generation"] is False

    # An explicit request cannot override the offline backend either.
    gen2 = HypothesisGenerator(model_name=DEFAULT_OFFLINE_MODEL)
    state2 = await gen2._prepare_generation(
        "goal", opts={"enable_tool_calling_generation": True}
    )
    assert state2["enable_tool_calling_generation"] is False
