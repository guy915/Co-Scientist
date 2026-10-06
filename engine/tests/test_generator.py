from __future__ import annotations

from typing import Any

import pytest

from co_scientist import mcp_client
from co_scientist.generator import run_setup
from co_scientist.generator.core import HypothesisGenerator
from co_scientist.generator.run_setup import GeneratorOptions
from co_scientist.offline.llm import DEFAULT_OFFLINE_MODEL
from co_scientist.scheduling import ALLOWED_LOOP_TASKS
from co_scientist.workflow_topology import TASK_ROUTES
from tests._mcp import stub_mcp_availability


def test_enable_cache_is_per_run_and_never_touches_process_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Singleton environment defaults would affect every run in the process,
    so an offline demo must not poison later ones."""
    monkeypatch.setenv("COSCIENTIST_CACHE_ENABLED", "true")
    off = HypothesisGenerator(options=GeneratorOptions(enable_cache=False))
    assert off.enable_cache is False
    assert HypothesisGenerator().enable_cache is None
    import os

    assert os.environ["COSCIENTIST_CACHE_ENABLED"] == "true"


def test_task_routes_reconcile_with_allowed_loop_tasks() -> None:
    assert {task.value for task in ALLOWED_LOOP_TASKS} == set(TASK_ROUTES)


async def test_availability_is_probed_once_per_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probes: list[Any] = []

    async def _probe(**kwargs: Any) -> bool:
        probes.append(kwargs.get("tool_registry"))
        return True

    from co_scientist import mcp_client

    monkeypatch.setattr(mcp_client, "check_mcp_available", _probe)
    monkeypatch.setattr(mcp_client, "check_literature_source_available", _probe)

    generator = HypothesisGenerator()
    await generator.prepare_task_state("goal one")
    await generator.prepare_task_state("goal two")
    assert len(probes) == 2, "one concurrent probe pair, cached afterward"

    generator.reload_tool_registry(tools_config=None, disable_tools=["pubmed"])
    await generator.prepare_task_state("goal three")
    assert len(probes) == 4, "a registry change must re-probe"


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
