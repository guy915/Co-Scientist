from __future__ import annotations

from typing import Any

import pytest

from co_scientist import mcp_client
from co_scientist.generator import run_setup
from co_scientist.generator.core import HypothesisGenerator
from co_scientist.offline.llm import DEFAULT_OFFLINE_MODEL
from tests._mcp import stub_mcp_availability


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
