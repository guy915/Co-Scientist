from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

import pytest
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph

from co_scientist.constants import (
    DEFAULT_EVOLUTION_MAX_COUNT,
    DEFAULT_INITIAL_HYPOTHESES_COUNT,
    DEFAULT_MAX_ITERATIONS,
)
from co_scientist.generator import GeneratorOptions, HypothesisGenerator
from co_scientist.generator.graph import (
    _add_workflow_edges,
    _add_workflow_nodes,
    _resume_router,
)
from co_scientist.models import ExecutionMetrics
from co_scientist.scheduling import ALLOWED_LOOP_TASKS, TaskType
from co_scientist.state import WorkflowState
from co_scientist.workflow_topology import TASK_ROUTES, route_next_task
from tests._mcp import stub_mcp_availability
from tests._state import make_hypothesis, make_state

# Node set the graph compiles with literature review enabled. ``__start__`` is
# LangGraph's implicit entry node; ``END`` does not appear as a node key.
_LIT_NODES = {
    "__start__",
    "supervisor",
    "literature_review",
    "generate",
    "reflection",
    "review",
    "comprehensive_reflection",
    "safety_screen",
    "ranking",
    "deep_verification",
    "orchestrator",
    "meta_review",
    "evolve",
    "proximity",
    "research_overview",
}

_SIMPLE_NODES = _LIT_NODES - {"literature_review", "reflection"}


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
    assert gen._graph is None
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


def test_build_graph_with_literature_review_compiles() -> None:
    gen = HypothesisGenerator()
    graph = gen._build_graph(enable_literature_review_node=True)
    assert isinstance(graph, CompiledStateGraph)
    assert set(graph.nodes.keys()) == _LIT_NODES


def test_build_graph_without_literature_review_omits_nodes() -> None:
    gen = HypothesisGenerator()
    graph = gen._build_graph(enable_literature_review_node=False)
    assert isinstance(graph, CompiledStateGraph)
    assert set(graph.nodes.keys()) == _SIMPLE_NODES
    assert "literature_review" not in graph.nodes
    assert "reflection" not in graph.nodes


def test_deep_verification_precedes_ranking() -> None:
    """No hypothesis may enter ranking before its core assumptions are
    probed."""
    gen = HypothesisGenerator()
    graph = gen._build_graph(enable_literature_review_node=False)
    drawable = graph.get_graph()
    safety_targets = {
        e.target for e in drawable.edges if e.source == "safety_screen"
    }
    ranking_targets = {
        e.target for e in drawable.edges if e.source == "ranking"
    }
    verification_targets = {
        e.target for e in drawable.edges if e.source == "deep_verification"
    }
    assert safety_targets == {"deep_verification"}
    assert verification_targets == {"ranking"}
    assert ranking_targets == {"orchestrator"}


def test_research_overview_is_the_only_terminal_node() -> None:
    gen = HypothesisGenerator()
    graph = gen._build_graph(enable_literature_review_node=False)
    drawable = graph.get_graph()
    end_sources = {e.source for e in drawable.edges if e.target == "__end__"}
    assert end_sources == {"research_overview"}


def test_graph_includes_deep_verification_node() -> None:
    gen = HypothesisGenerator(model_name="test/model")
    graph = gen._build_graph(enable_literature_review_node=False)
    assert "deep_verification" in graph.nodes


def test_graph_includes_research_overview_node_and_terminates_through_it() -> (
    None
):
    gen = HypothesisGenerator(model_name="test/model")
    graph = gen._build_graph(enable_literature_review_node=False)
    assert "research_overview" in graph.nodes


_NO_LIT_REVIEW: dict[str, Any] = {"enable_literature_review_node": False}


class _FakeCompiledGraph:
    def __init__(
        self,
        *,
        final_state: WorkflowState | None = None,
        invoke_error: Exception | None = None,
        chunks: Sequence[dict[str, dict[str, Any]]] = (),
        stream_error: Exception | None = None,
    ) -> None:
        self._final_state = final_state
        self._invoke_error = invoke_error
        self._chunks = chunks
        self._stream_error = stream_error

    async def ainvoke(
        self, state: WorkflowState, config: dict[str, int]
    ) -> WorkflowState:
        if self._invoke_error is not None:
            raise self._invoke_error
        assert self._final_state is not None
        return self._final_state

    async def astream(
        self, state: WorkflowState, config: dict[str, int]
    ) -> AsyncIterator[dict[str, dict[str, Any]]]:
        for chunk in self._chunks:
            yield chunk
        if self._stream_error is not None:
            raise self._stream_error


def _install_fake_graph(
    gen: HypothesisGenerator, graph: _FakeCompiledGraph
) -> None:
    gen._graph = cast(Any, graph)


async def test_stream_false_returns_coroutine_that_resolves_to_result() -> None:
    gen = HypothesisGenerator()
    final_state = make_state(
        hypotheses=[make_hypothesis("Final hypothesis")],
        metrics=ExecutionMetrics(hypothesis_count=1, llm_calls=3),
        meta_review={"summary": "done"},
    )
    _install_fake_graph(gen, _FakeCompiledGraph(final_state=final_state))

    coro = gen.generate_hypotheses("goal", opts=_NO_LIT_REVIEW, stream=False)
    assert inspect.iscoroutine(coro)

    result = await coro
    assert len(result["hypotheses"]) == 1
    assert result["hypotheses"][0]["text"] == "Final hypothesis"
    assert result["meta_review"] == {"summary": "done"}
    assert result["metrics"]["llm_calls"] == 3
    assert result["execution_time"] >= 0.0


async def test_non_streaming_propagates_graph_errors() -> None:
    gen = HypothesisGenerator()
    boom = RuntimeError("ainvoke exploded")
    _install_fake_graph(gen, _FakeCompiledGraph(invoke_error=boom))

    with pytest.raises(RuntimeError, match="ainvoke exploded"):
        await gen.generate_hypotheses("goal", opts=_NO_LIT_REVIEW, stream=False)


async def test_stream_true_returns_async_iterator_yielding_each_node() -> None:
    gen = HypothesisGenerator()
    chunks: list[dict[str, dict[str, Any]]] = [
        {"supervisor": {"supervisor_guidance": {"plan": "p1"}}},
        {
            "generate": {
                "hypotheses": [make_hypothesis("streamed h")],
                "metrics": ExecutionMetrics(llm_calls=1),
            }
        },
    ]
    _install_fake_graph(gen, _FakeCompiledGraph(chunks=chunks))

    result = gen.generate_hypotheses("goal", opts=_NO_LIT_REVIEW, stream=True)
    assert not inspect.iscoroutine(result)
    assert hasattr(result, "__anext__")

    seen: list[tuple[str, dict[str, Any]]] = []
    async for node_name, state_dict in result:
        seen.append((node_name, state_dict))

    assert [name for name, _ in seen] == ["supervisor", "generate"]
    _, final_payload = seen[-1]
    assert final_payload["research_plan"] == {"plan": "p1"}
    assert final_payload["hypotheses"][0]["text"] == "streamed h"
    assert final_payload["metrics"]["llm_calls"] == 1


async def test_streaming_propagates_errors_raised_mid_stream() -> None:
    gen = HypothesisGenerator()
    boom = RuntimeError("astream exploded")
    chunks: list[dict[str, dict[str, Any]]] = [
        {"supervisor": {"supervisor_guidance": {"plan": "p1"}}}
    ]
    _install_fake_graph(
        gen, _FakeCompiledGraph(chunks=chunks, stream_error=boom)
    )

    seen: list[tuple[str, dict[str, Any]]] = []
    with pytest.raises(RuntimeError, match="astream exploded"):
        async for node_name, state_dict in gen.generate_hypotheses(
            "goal", opts=_NO_LIT_REVIEW, stream=True
        ):
            seen.append((node_name, state_dict))

    assert len(seen) == 1


def _inbound_edges(
    enable_literature_review_node: bool,
) -> dict[str, set[tuple[str, bool]]]:
    workflow = StateGraph(WorkflowState)
    _add_workflow_nodes(workflow, enable_literature_review_node)
    _add_workflow_edges(workflow, enable_literature_review_node)
    graph = workflow.compile().get_graph()
    inbound: dict[str, set[tuple[str, bool]]] = {}
    for edge in graph.edges:
        inbound.setdefault(edge.target, set()).add(
            (edge.source, edge.conditional)
        )
    return inbound


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


@pytest.mark.parametrize("enable_literature_review_node", [True, False])
def test_supervisor_plan_is_synthesized_once_never_revisited(
    enable_literature_review_node: bool,
) -> None:
    inbound = _inbound_edges(enable_literature_review_node)
    assert inbound["supervisor"] == {("__start__", True)}


@pytest.mark.parametrize("enable_literature_review_node", [True, False])
def test_orchestrator_is_the_per_cycle_loop_point(
    enable_literature_review_node: bool,
) -> None:
    inbound_sources = {
        source
        for source, _ in _inbound_edges(enable_literature_review_node)[
            "orchestrator"
        ]
    }
    assert {"__start__", "ranking", "proximity"} <= inbound_sources


def test_fresh_run_enters_supervisor_resume_bypasses_it() -> None:
    assert _resume_router(make_state()) == "supervisor"
    assert _resume_router(make_state(resume=True)) == "orchestrator"


def _nodes(generator: HypothesisGenerator) -> set[str]:
    assert generator._graph is not None
    return set(generator._graph.nodes)


async def test_disabling_literature_review_rebuilds_the_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=True)
    generator = HypothesisGenerator()

    await generator.prepare_task_state("goal one")
    assert "literature_review" in _nodes(generator)

    await generator.prepare_task_state(
        "goal two", opts={"enable_literature_review_node": False}
    )
    assert "literature_review" not in _nodes(generator)
    assert "reflection" not in _nodes(generator)


async def test_enabling_literature_review_rebuilds_the_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=True)
    generator = HypothesisGenerator()

    await generator.prepare_task_state(
        "goal one", opts={"enable_literature_review_node": False}
    )
    assert "literature_review" not in _nodes(generator)

    await generator.prepare_task_state("goal two")
    assert "literature_review" in _nodes(generator)


async def test_unchanged_configuration_keeps_the_compiled_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=True)
    generator = HypothesisGenerator()

    await generator.prepare_task_state("goal one")
    first = generator._graph
    await generator.prepare_task_state("goal two")
    assert generator._graph is first


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


async def test_reloading_the_registry_invalidates_the_graph(
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
