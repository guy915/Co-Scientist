from __future__ import annotations

from typing import Any

import pytest

from co_scientist.generator.core import HypothesisGenerator
from co_scientist.generator.run_setup import GeneratorOptions
from co_scientist.scheduling import ALLOWED_LOOP_TASKS
from co_scientist.workflow_topology import TASK_ROUTES


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
