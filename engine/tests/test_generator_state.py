from __future__ import annotations

from typing import Any

import pytest

from co_scientist import mcp_client
from co_scientist.generator import run_setup
from co_scientist.generator.core import HypothesisGenerator
from co_scientist.generator.run_setup import GeneratorOptions
from co_scientist.offline.llm import DEFAULT_OFFLINE_MODEL
from tests._mcp import stub_mcp_availability


async def test_prepare_task_state_carries_config_and_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator(
        model_name="m",
        max_iterations=2,
        initial_hypotheses_count=7,
        evolution_max_count=4,
        options=GeneratorOptions(supervisor_model_name="sup"),
    )
    state = await gen.prepare_task_state(
        "Cure X",
        run_id="fixed-id",
        opts={
            "preferences": "pref-X",
            "attributes": ["attr-Y"],
            "constraints": ["cons-Z"],
            "lab_constraints": ["zebrafish only"],
            "user_inputs": {
                "starting_hypotheses": ["h1"],
                "literature": ["lit1"],
            },
        },
    )
    assert state["research_goal"] == "Cure X"
    assert state["run_id"] == "fixed-id"
    assert state["model_name"] == "m"
    assert state["supervisor_model_name"] == "sup"
    assert state["max_iterations"] == 2
    assert state["initial_hypotheses_count"] == 7
    assert state["evolution_max_count"] == 4
    assert state["hypotheses"] == []
    assert state["current_iteration"] == 0
    assert state["preferences"] == "pref-X"
    assert state["attributes"] == ["attr-Y"]
    assert state["constraints"] == ["cons-Z"]
    assert state["lab_constraints"] == ["zebrafish only"]
    assert state["starting_hypotheses"] == ["h1"]
    assert state["literature"] == ["lit1"]
    assert state["tool_registry"] is gen._tool_registry


async def test_prepare_task_state_defaults_when_no_options_are_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=False)
    monkeypatch.delenv("COSCIENTIST_DEV_MODE", raising=False)
    state = await HypothesisGenerator().prepare_task_state("goal")
    assert state["run_id"]
    for key in (
        "preferences",
        "attributes",
        "constraints",
        "lab_constraints",
        "starting_hypotheses",
        "literature",
    ):
        assert state[key] is None
    assert state["enable_tool_calling_generation"] is False
    assert state["dev_test_lit_tools_isolation"] is False
    assert state["dev_mode"] is False


@pytest.mark.parametrize(
    ("env", "opt", "expected"),
    [("true", None, True), ("true", False, False), (None, True, True)],
)
async def test_dev_mode_comes_from_the_environment_unless_the_option_says(
    monkeypatch: pytest.MonkeyPatch,
    env: str | None,
    opt: bool | None,
    expected: bool,
) -> None:
    """Environment configuration enters at the run boundary, not inside node
    execution."""
    stub_mcp_availability(monkeypatch, available=False)
    if env is None:
        monkeypatch.delenv("COSCIENTIST_DEV_MODE", raising=False)
    else:
        monkeypatch.setenv("COSCIENTIST_DEV_MODE", env)
    opts = {} if opt is None else {"dev_mode": opt}
    state = await HypothesisGenerator().prepare_task_state("goal", opts=opts)
    assert state["dev_mode"] is expected


async def test_mcp_availability_is_probed_once_per_instance(
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
    state = await gen.prepare_task_state("goal")
    after_first = calls["n"]
    await gen.prepare_task_state("goal again")
    assert calls["n"] == after_first
    assert state["mcp_available"] is True
    assert state["pubmed_available"] is True


async def test_explicit_disable_skips_mcp_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    async def explode(**_: Any) -> bool:
        raise AssertionError("MCP probe should not be called")

    monkeypatch.setattr(mcp_client, "check_mcp_available", explode)
    monkeypatch.setattr(
        mcp_client, "check_literature_source_available", explode
    )

    state = await HypothesisGenerator().prepare_task_state(
        "goal",
        opts={
            "enable_literature_review_node": False,
            "enable_tool_calling_generation": True,
        },
    )
    assert state["mcp_available"] is False
    assert state["enable_tool_calling_generation"] is False


@pytest.mark.parametrize(
    ("available", "opt", "model", "expected"),
    [
        (True, None, None, False),  # opt-in: transcripts multiply cost
        (True, True, None, True),
        (True, False, None, False),
        (False, True, None, False),
        # The offline responder emits no tool calls.
        (True, True, DEFAULT_OFFLINE_MODEL, False),
    ],
)
async def test_tool_calling_generation_requires_opt_in_and_capability(
    monkeypatch: pytest.MonkeyPatch,
    available: bool,
    opt: bool | None,
    model: str | None,
    expected: bool,
) -> None:
    stub_mcp_availability(monkeypatch, available=available)
    gen = (
        HypothesisGenerator(model_name=model)
        if model
        else HypothesisGenerator()
    )
    opts = {} if opt is None else {"enable_tool_calling_generation": opt}
    state = await gen.prepare_task_state("goal", opts=opts)
    assert state["enable_tool_calling_generation"] is expected


@pytest.mark.parametrize(
    ("options", "model", "expected"),
    [
        ({"enable_overview_review": True}, "offline/deterministic", False),
        ({"enable_overview_review": True}, "deepseek/some-model", True),
        ({}, "deepseek/some-model", False),
    ],
)
def test_overview_review_needs_a_real_model_and_an_explicit_request(
    options: dict[str, Any], model: str, expected: bool
) -> None:
    assert run_setup._resolve_overview_review(options, model) is expected
