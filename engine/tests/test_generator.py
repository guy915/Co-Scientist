from __future__ import annotations

from typing import Any

import pytest

from co_scientist.constants import (
    DEFAULT_EVOLUTION_MAX_COUNT,
    DEFAULT_INITIAL_HYPOTHESES_COUNT,
    DEFAULT_MAX_ITERATIONS,
)
from co_scientist.generator.core import HypothesisGenerator
from co_scientist.generator.run_setup import GeneratorOptions
from co_scientist.scheduling import ALLOWED_LOOP_TASKS, TaskType
from co_scientist.workflow_topology import TASK_ROUTES, route_next_task
from tests._mcp import stub_mcp_availability
from tests._state import make_state


def test_defaults_match_constants() -> None:
    gen = HypothesisGenerator()
    assert gen.model_name == "deepseek/deepseek-v4-flash"
    assert gen.max_iterations == DEFAULT_MAX_ITERATIONS
    assert gen.initial_hypotheses_count == DEFAULT_INITIAL_HYPOTHESES_COUNT
    assert gen.evolution_max_count == DEFAULT_EVOLUTION_MAX_COUNT


def test_config_overrides_are_stored() -> None:
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
    gen = HypothesisGenerator(model_name="only-model")
    assert gen.supervisor_model_name == "only-model"


def test_supervisor_model_override_is_independent() -> None:
    gen = HypothesisGenerator(
        model_name="base",
        options=GeneratorOptions(
            supervisor_model_name="sup",
        ),
    )
    assert gen.model_name == "base"
    assert gen.supervisor_model_name == "sup"


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


def test_enable_cache_is_stored_on_the_instance() -> None:
    assert (
        HypothesisGenerator(
            options=GeneratorOptions(
                enable_cache=True,
            ),
        ).enable_cache
        is True
    )
    assert (
        HypothesisGenerator(
            options=GeneratorOptions(
                enable_cache=False,
            ),
        ).enable_cache
        is False
    )
    assert HypothesisGenerator().enable_cache is None


def test_enable_cache_never_touches_process_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache enablement is per-run; singleton environment defaults affect all
    runs."""
    monkeypatch.delenv("COSCIENTIST_CACHE_ENABLED", raising=False)
    HypothesisGenerator(
        options=GeneratorOptions(
            enable_cache=True,
        ),
    )
    HypothesisGenerator(
        options=GeneratorOptions(
            enable_cache=False,
        ),
    )
    HypothesisGenerator()
    import os

    assert "COSCIENTIST_CACHE_ENABLED" not in os.environ


def test_offline_generator_construction_does_not_disable_process_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline demo construction must not poison later runs in the same
    process."""
    monkeypatch.setenv("COSCIENTIST_CACHE_ENABLED", "true")
    HypothesisGenerator(
        options=GeneratorOptions(
            enable_cache=False,
        ),
    )
    import os

    assert os.environ["COSCIENTIST_CACHE_ENABLED"] == "true"
    real_gen = HypothesisGenerator()
    assert real_gen.enable_cache is None


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


def test_cache_dir_unset_leaves_env_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COSCIENTIST_CACHE_DIR", raising=False)
    HypothesisGenerator()
    import os

    assert "COSCIENTIST_CACHE_DIR" not in os.environ


_NO_LIT_REVIEW: dict[str, Any] = {"enable_literature_review_node": False}


def test_task_routes_reconcile_with_allowed_loop_tasks() -> None:
    assert {task.value for task in ALLOWED_LOOP_TASKS} == set(TASK_ROUTES)


def test_routes_each_task_type_to_its_node() -> None:
    for task in ALLOWED_LOOP_TASKS:
        state = make_state(next_task=task.value)
        assert route_next_task(state) == TASK_ROUTES[task.value]


def test_evolve_routes_through_meta_review() -> None:
    state = make_state(next_task=TaskType.EVOLVE.value)
    assert route_next_task(state) == "meta_review"


def test_terminate_routes_to_research_overview() -> None:
    state = make_state(next_task=TaskType.TERMINATE.value)
    assert route_next_task(state) == "research_overview"


def test_missing_next_task_falls_back_to_synthesis() -> None:
    state = make_state(next_task=None)
    assert route_next_task(state) == "research_overview"


def test_unknown_next_task_falls_back_to_synthesis() -> None:
    state = make_state(next_task="bogus")
    assert route_next_task(state) == "research_overview"


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
