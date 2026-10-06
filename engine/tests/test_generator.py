from __future__ import annotations

from typing import Any

import pytest

from co_scientist.generator.core import HypothesisGenerator
from co_scientist.generator.run_setup import GeneratorOptions
from co_scientist.scheduling import ALLOWED_LOOP_TASKS, TaskType
from co_scientist.workflow_topology import TASK_ROUTES, route_next_task
from tests._mcp import stub_mcp_availability
from tests._state import make_state


def test_lazy_state_is_unset_before_first_run() -> None:
    gen = HypothesisGenerator()
    assert gen._mcp_available is None
    assert gen._pubmed_available is None
    assert gen._tool_registry is not None
    workflow = gen._tool_registry.get_workflow("literature_review")
    assert workflow is not None and workflow.is_multi_source()
    # The literature review searches the public databases; the group's own
    # papers reach a run as an injected catalog, not as a search source.
    assert [
        source.tool for source in workflow.get_enabled_search_sources()
    ] == [
        "pubmed_fulltext",
        "openalex_search",
        "europepmc_search",
        "web_search",
        "arxiv_search",
        "biorxiv_search",
    ]


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


def test_cache_dir_sets_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production does not pass cache_dir; it still sets the process default."""
    monkeypatch.delenv("COSCIENTIST_CACHE_DIR", raising=False)
    HypothesisGenerator(
        options=GeneratorOptions(
            cache_dir="/tmp/coscientist-test-cache",
        ),
    )
    import os

    assert os.environ["COSCIENTIST_CACHE_DIR"] == "/tmp/coscientist-test-cache"


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


async def test_reloading_the_registry_updates_prepared_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=True)
    generator = HypothesisGenerator()
    state = await generator.prepare_task_state("goal one")
    first_registry = state["tool_registry"]

    generator.reload_tool_registry(tools_config=None, disable_tools=["pubmed"])
    state = await generator.prepare_task_state("goal two")

    reloaded = generator._tool_registry
    assert reloaded is not None
    # Reading before identity checks avoids mypy widening this to Optional.
    assert "pubmed" not in reloaded.get_enabled_tools()
    assert state["tool_registry"] is not first_registry
    assert state["tool_registry"] is reloaded


@pytest.mark.parametrize("next_task", [None, "bogus", "terminate"])
def test_missing_or_unknown_next_task_falls_back_to_synthesis(
    next_task: str | None,
) -> None:
    state = make_state(next_task=next_task)
    assert route_next_task(state) == "research_overview"


@pytest.mark.parametrize("task", sorted(ALLOWED_LOOP_TASKS, key=str))
def test_each_loop_task_routes_to_its_node(task: TaskType) -> None:
    assert (
        route_next_task(make_state(next_task=task.value))
        == (TASK_ROUTES[task.value])
    )
    assert route_next_task(make_state(next_task="evolve")) == "meta_review"
