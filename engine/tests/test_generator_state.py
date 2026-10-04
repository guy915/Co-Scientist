from __future__ import annotations

from typing import Any

import pytest

from co_scientist import mcp_client
from co_scientist.generator import run_setup
from co_scientist.generator.core import HypothesisGenerator
from co_scientist.generator.run_setup import GeneratorOptions
from tests._mcp import stub_mcp_availability


async def test_prepare_task_state_populates_core_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    state = await gen.prepare_task_state("Cure X")
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


async def test_prepare_task_state_generates_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["run_id"]


async def test_prepare_task_state_honors_explicit_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal", run_id="fixed-id")
    assert state["run_id"] == "fixed-id"


async def test_prepare_task_state_passes_through_opts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    opts = {
        "preferences": "pref-X",
        "attributes": ["attr-Y"],
        "constraints": ["cons-Z"],
        "lab_constraints": ["zebrafish only"],
        "user_inputs": {
            "starting_hypotheses": ["h1"],
            "literature": ["lit1"],
        },
    }
    state = await gen.prepare_task_state("goal", opts=opts)
    assert state["preferences"] == "pref-X"
    assert state["attributes"] == ["attr-Y"]
    assert state["constraints"] == ["cons-Z"]
    assert state["lab_constraints"] == ["zebrafish only"]
    assert state["starting_hypotheses"] == ["h1"]
    assert state["literature"] == ["lit1"]


async def test_prepare_task_state_opt_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["preferences"] is None
    assert state["attributes"] is None
    assert state["constraints"] is None
    assert state["lab_constraints"] is None
    assert state["starting_hypotheses"] is None
    assert state["literature"] is None
    assert state["enable_tool_calling_generation"] is False
    assert state["dev_test_lit_tools_isolation"] is False


async def test_prepare_task_state_dev_isolation_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal", opts={"dev_test_lit_tools_isolation": True}
    )
    assert state["dev_test_lit_tools_isolation"] is True


async def test_prepare_task_state_reads_dev_mode_env_into_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Environment configuration enters at the run boundary, not inside node
    execution."""
    stub_mcp_availability(monkeypatch, available=False)
    monkeypatch.setenv("COSCIENTIST_DEV_MODE", "true")
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["dev_mode"] is True


async def test_prepare_task_state_dev_mode_opt_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=False)
    monkeypatch.setenv("COSCIENTIST_DEV_MODE", "true")
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal", opts={"dev_mode": False})
    assert state["dev_mode"] is False

    monkeypatch.delenv("COSCIENTIST_DEV_MODE", raising=False)
    state = await gen.prepare_task_state("goal", opts={"dev_mode": True})
    assert state["dev_mode"] is True


async def test_prepare_task_state_dev_mode_defaults_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=False)
    monkeypatch.delenv("COSCIENTIST_DEV_MODE", raising=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["dev_mode"] is False


async def test_mcp_available_enables_literature_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["mcp_available"] is True
    assert state["pubmed_available"] is True


async def test_mcp_unavailable_disables_literature_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["mcp_available"] is False


async def test_mcp_availability_cached_per_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    async def counting(**_: Any) -> bool:
        calls["n"] += 1
        return True

    monkeypatch.setattr(mcp_client, "check_mcp_available", counting)
    monkeypatch.setattr(
        mcp_client, "check_literature_source_available", counting
    )

    gen = HypothesisGenerator()
    await gen.prepare_task_state("goal")
    after_first = calls["n"]
    await gen.prepare_task_state("goal again")
    assert calls["n"] == after_first
    assert gen._mcp_available is True


async def test_explicit_disable_skips_mcp_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    async def explode(**_: Any) -> bool:
        raise AssertionError("MCP probe should not be called")

    monkeypatch.setattr(mcp_client, "check_mcp_available", explode)
    monkeypatch.setattr(
        mcp_client, "check_literature_source_available", explode
    )

    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal", opts={"enable_literature_review_node": False}
    )
    assert state["mcp_available"] is False


async def test_tool_calling_honored_when_mcp_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal", opts={"enable_tool_calling_generation": True}
    )
    assert state["enable_tool_calling_generation"] is True


async def test_tool_calling_disabled_when_mcp_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal", opts={"enable_tool_calling_generation": True}
    )
    assert state["enable_tool_calling_generation"] is False


async def test_tool_calling_with_lit_disabled_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal",
        opts={
            "enable_literature_review_node": False,
            "enable_tool_calling_generation": True,
        },
    )
    assert state["enable_tool_calling_generation"] is False
    assert state["mcp_available"] is False


async def test_tool_calling_off_by_default_when_tools_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Availability is not opt-in: tool transcripts multiply cost per
    hypothesis and cycle."""
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["enable_tool_calling_generation"] is False


async def test_tool_calling_opt_in_survives_prepare_task_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal", opts={"enable_tool_calling_generation": True}
    )
    assert state["enable_tool_calling_generation"] is True


async def test_tool_calling_explicit_opt_out_honored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal", opts={"enable_tool_calling_generation": False}
    )
    assert state["enable_tool_calling_generation"] is False


async def test_tool_calling_stays_off_by_default_without_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["enable_tool_calling_generation"] is False


async def test_tool_calling_forced_off_for_offline_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The offline responder emits no tool calls; a tool-loop reply cannot
    satisfy its parser."""
    from co_scientist.offline.llm import DEFAULT_OFFLINE_MODEL

    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator(model_name=DEFAULT_OFFLINE_MODEL)
    state = await gen.prepare_task_state("goal")
    assert state["enable_tool_calling_generation"] is False

    gen2 = HypothesisGenerator(model_name=DEFAULT_OFFLINE_MODEL)
    state2 = await gen2.prepare_task_state(
        "goal", opts={"enable_tool_calling_generation": True}
    )
    assert state2["enable_tool_calling_generation"] is False


def test_offline_backend_runs_no_review_at_all() -> None:
    assert (
        run_setup._resolve_overview_review(
            {"enable_overview_review": True}, "offline/deterministic"
        )
        is False
    )


def test_a_real_model_asked_for_may_review() -> None:
    assert (
        run_setup._resolve_overview_review(
            {"enable_overview_review": True}, "deepseek/some-model"
        )
        is True
    )


def test_an_omitted_option_is_not_a_request() -> None:
    assert (
        run_setup._resolve_overview_review({}, "deepseek/some-model") is False
    )
