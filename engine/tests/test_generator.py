"""Offline contracts for generator."""

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

# Node set for the simplified flow (no literature_review / reflection).
_SIMPLE_NODES = _LIT_NODES - {"literature_review", "reflection"}


# --- Construction / configuration -------------------------------------------


def test_defaults_match_constants() -> None:
    """Unspecified counts fall back to the module-level defaults."""
    gen = HypothesisGenerator()
    assert gen.model_name == "deepseek/deepseek-v4-flash"
    assert gen.max_iterations == DEFAULT_MAX_ITERATIONS
    assert gen.initial_hypotheses_count == DEFAULT_INITIAL_HYPOTHESES_COUNT
    assert gen.evolution_max_count == DEFAULT_EVOLUTION_MAX_COUNT


def test_config_overrides_are_stored() -> None:
    """Explicit constructor arguments are held verbatim on the instance."""
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
    """When no supervisor model is given it mirrors ``model_name``."""
    gen = HypothesisGenerator(model_name="only-model")
    assert gen.supervisor_model_name == "only-model"


def test_supervisor_model_override_is_independent() -> None:
    """An explicit supervisor model is kept distinct from ``model_name``."""
    gen = HypothesisGenerator(
        model_name="base",
        options=GeneratorOptions(
            supervisor_model_name="sup",
        ),
    )
    assert gen.model_name == "base"
    assert gen.supervisor_model_name == "sup"


def test_lazy_state_is_unset_before_first_run() -> None:
    """Graph/probes are lazy while bundled scientific tools are ready."""
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
    """``enable_cache`` is held verbatim for this generator's own runs."""
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
    """Neither ``enable_cache`` value mutates ``COSCIENTIST_CACHE_ENABLED``.

    Regression test: the constructor used to export
    ``COSCIENTIST_CACHE_ENABLED`` from ``enable_cache`` directly, and
    ``cache.get_cache()`` memoizes that env var once per process --
    whichever generator's constructor ran first "won" the setting for
    every other generator's calls for the rest of the process lifetime
    (see a production incident where the offline demo seeder's
    ``enable_cache=False`` disabled caching for every later real run in
    the same embedded worker). ``enable_cache`` is now applied per-run via
    ``cache.scoped_cache_override`` instead (see ``generator/core.py``),
    so construction alone must never touch the env var either way.
    """
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
    """Building a cache-disabled generator must not poison a later one.

    The exact production scenario: an ``enable_cache=False`` generator
    (the app's offline/demo backend) is constructed first, then a plain
    generator (a real run) is constructed afterward in the same process.
    The env var a real run relies on as its process default must be
    unaffected by the disabled generator having existed.
    """
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
    """``cache_dir`` exports the cache-directory env var.

    Unlike ``enable_cache``, nothing passes ``cache_dir`` in production
    today, so it is left mutating the process-wide default as it always
    has (see ``generator/run_setup.py::_configure_cache_dir_env``).
    """
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
    """With ``cache_dir`` left as None the constructor sets no env var."""
    monkeypatch.delenv("COSCIENTIST_CACHE_DIR", raising=False)
    HypothesisGenerator()
    import os

    assert "COSCIENTIST_CACHE_DIR" not in os.environ


# --- Graph compilation -------------------------------------------------------


def test_build_graph_with_literature_review_compiles() -> None:
    """The full flow compiles to a CompiledStateGraph with all nodes."""
    gen = HypothesisGenerator()
    graph = gen._build_graph(enable_literature_review_node=True)
    assert isinstance(graph, CompiledStateGraph)
    assert set(graph.nodes.keys()) == _LIT_NODES


def test_build_graph_without_literature_review_omits_nodes() -> None:
    """The simplified flow drops the literature_review and reflection nodes."""
    gen = HypothesisGenerator()
    graph = gen._build_graph(enable_literature_review_node=False)
    assert isinstance(graph, CompiledStateGraph)
    assert set(graph.nodes.keys()) == _SIMPLE_NODES
    assert "literature_review" not in graph.nodes
    assert "reflection" not in graph.nodes


def test_deep_verification_precedes_ranking() -> None:
    """Verification guards tournament entry (``03-reflection.md``).

    ``ReviewHypothesis`` performs the deep verification and only then
    creates that hypothesis's ``AddToTournament`` task, so the safety
    screen hands into verification, verification into the tournament, and
    the tournament on to the loop point.
    """
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
    """Every terminal path flows through research_overview before END."""
    gen = HypothesisGenerator()
    graph = gen._build_graph(enable_literature_review_node=False)
    drawable = graph.get_graph()
    end_sources = {e.source for e in drawable.edges if e.target == "__end__"}
    assert end_sources == {"research_overview"}


# --- prepare_task_state: state building -------------------------------------


def test_graph_includes_deep_verification_node() -> None:
    """The graph registers a post-tournament deep_verification node."""
    gen = HypothesisGenerator(model_name="test/model")
    graph = gen._build_graph(enable_literature_review_node=False)
    assert "deep_verification" in graph.nodes


def test_graph_includes_research_overview_node_and_terminates_through_it() -> (
    None
):
    """The graph registers a terminal research_overview node."""
    gen = HypothesisGenerator(model_name="test/model")
    graph = gen._build_graph(enable_literature_review_node=False)
    assert "research_overview" in graph.nodes


_NO_LIT_REVIEW: dict[str, Any] = {"enable_literature_review_node": False}


class _FakeCompiledGraph:
    """Stub compiled workflow graph for exercising the generator's run paths.

    Supports both ``ainvoke`` (non-streaming) and ``astream`` (streaming)
    with canned responses, plus optional errors to exercise the generator's
    exception-propagation branches.
    """

    def __init__(
        self,
        *,
        final_state: WorkflowState | None = None,
        invoke_error: Exception | None = None,
        chunks: Sequence[dict[str, dict[str, Any]]] = (),
        stream_error: Exception | None = None,
    ) -> None:
        """Configures the stub's canned ``ainvoke``/``astream`` behavior.

        Args:
            final_state: The state ``ainvoke`` returns, when not erroring.
            invoke_error: If set, ``ainvoke`` raises this instead of
                returning ``final_state``.
            chunks: The sequence of ``{node_name: node_state}`` dicts that
                ``astream`` yields, in order.
            stream_error: If set, raised after all ``chunks`` are yielded.
        """
        self._final_state = final_state
        self._invoke_error = invoke_error
        self._chunks = chunks
        self._stream_error = stream_error

    async def ainvoke(
        self, state: WorkflowState, config: dict[str, int]
    ) -> WorkflowState:
        """Returns the configured final state, or raises ``invoke_error``."""
        if self._invoke_error is not None:
            raise self._invoke_error
        assert self._final_state is not None
        return self._final_state

    async def astream(
        self, state: WorkflowState, config: dict[str, int]
    ) -> AsyncIterator[dict[str, dict[str, Any]]]:
        """Yields the configured chunks, then raises ``stream_error`` if set."""
        for chunk in self._chunks:
            yield chunk
        if self._stream_error is not None:
            raise self._stream_error


def _install_fake_graph(
    gen: HypothesisGenerator, graph: _FakeCompiledGraph
) -> None:
    """Pre-installs a fake compiled graph so ``_ensure_graph_built`` no-ops.

    Args:
        gen: The generator under test.
        graph: The fake graph to install in place of a real compiled one.
    """
    gen._graph = cast(Any, graph)


# --- generate_hypotheses(stream=False) --------------------------------------


async def test_stream_false_returns_coroutine_that_resolves_to_result() -> None:
    """stream=False returns an awaitable resolving to the shaped result."""
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
    """A graph.ainvoke failure propagates unchanged to the caller."""
    gen = HypothesisGenerator()
    boom = RuntimeError("ainvoke exploded")
    _install_fake_graph(gen, _FakeCompiledGraph(invoke_error=boom))

    with pytest.raises(RuntimeError, match="ainvoke exploded"):
        await gen.generate_hypotheses("goal", opts=_NO_LIT_REVIEW, stream=False)


# --- generate_hypotheses(stream=True) ---------------------------------------


async def test_stream_true_returns_async_iterator_yielding_each_node() -> None:
    """stream=True returns an async iterator of (node_name, state) tuples."""
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
    # After the second chunk, cumulative state reflects both updates.
    _, final_payload = seen[-1]
    assert final_payload["research_plan"] == {"plan": "p1"}
    assert final_payload["hypotheses"][0]["text"] == "streamed h"
    assert final_payload["metrics"]["llm_calls"] == 1


async def test_streaming_propagates_errors_raised_mid_stream() -> None:
    """A graph.astream failure after some chunks still propagates."""
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
    """Map each node to its inbound ``(source, conditional)`` edges.

    Compiles the real workflow topology for the given flow shape and reads
    the edge set back, so the assertions below pin the graph as wired rather
    than the routing functions in isolation.
    """
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
    """The routing table and the scheduler's dispatchable set stay in sync.

    ``scheduling.policy.ALLOWED_LOOP_TASKS`` and
    ``workflow_topology.TASK_ROUTES`` each carry a "keep in sync" comment
    pointing at the other; this pins the invariant programmatically: the
    routing table's keys are exactly the task values the scheduler may
    dispatch at the loop point.
    """
    assert {task.value for task in ALLOWED_LOOP_TASKS} == set(TASK_ROUTES)


def test_routes_each_task_type_to_its_node() -> None:
    """Every task the orchestrator can emit maps to a real entry node."""
    for task in ALLOWED_LOOP_TASKS:
        state = make_state(next_task=task.value)
        assert route_next_task(state) == TASK_ROUTES[task.value]


def test_evolve_routes_through_meta_review() -> None:
    """EVOLVE enters at meta_review so the critique feeds evolve."""
    state = make_state(next_task=TaskType.EVOLVE.value)
    assert route_next_task(state) == "meta_review"


def test_terminate_routes_to_research_overview() -> None:
    """TERMINATE routes to the terminal synthesis node."""
    state = make_state(next_task=TaskType.TERMINATE.value)
    assert route_next_task(state) == "research_overview"


def test_missing_next_task_falls_back_to_synthesis() -> None:
    """A missing decision never dead-ends; it routes to synthesis."""
    state = make_state(next_task=None)
    assert route_next_task(state) == "research_overview"


def test_unknown_next_task_falls_back_to_synthesis() -> None:
    """An unrecognized next_task value routes to synthesis, not a crash."""
    state = make_state(next_task="bogus")
    assert route_next_task(state) == "research_overview"


# --- SUP-SPLIT-001: plan synthesized once at entry, decisions every cycle ---
# The published supervisor listing (corpus MA-4, `01-supervisor.md`) parses the
# goal into a ResearchPlan and SAVEs it exactly once, before the main WHILE
# loop; neither ManageFollowUpTasks nor DecideNextSteps ever revisits it.
# DecideNextSteps is the per-idle-pass decision point (run a tournament batch,
# evolve if stalled, periodic meta-review/overview) against that fixed plan.
# Our topology mirrors that pair: `supervisor` is the entry-only planner and
# `orchestrator` is the loop point. These tests pin that behaviour so the row
# stays honest.


@pytest.mark.parametrize("enable_literature_review_node", [True, False])
def test_supervisor_plan_is_synthesized_once_never_revisited(
    enable_literature_review_node: bool,
) -> None:
    """The supervisor is reachable only at entry, so its plan is built once.

    Its sole inbound edge is the entry conditional from START; no node loops
    back to it, so the plan it synthesizes is never re-synthesized mid-run --
    matching `StartCoScientist`, which parses the plan before the main loop.
    """
    inbound = _inbound_edges(enable_literature_review_node)
    assert inbound["supervisor"] == {("__start__", True)}


@pytest.mark.parametrize("enable_literature_review_node", [True, False])
def test_orchestrator_is_the_per_cycle_loop_point(
    enable_literature_review_node: bool,
) -> None:
    """The orchestrator is re-entered every cycle to decide the next step.

    It is fed by the ranking and proximity nodes each pass (and by START on a
    resumed run), which is the `DecideNextSteps` decision point -- run against
    the fixed plan, never re-planning it.
    """
    inbound_sources = {
        source
        for source, _ in _inbound_edges(enable_literature_review_node)[
            "orchestrator"
        ]
    }
    assert {"__start__", "ranking", "proximity"} <= inbound_sources


def test_fresh_run_enters_supervisor_resume_bypasses_it() -> None:
    """A fresh run plans; a resumed run re-enters at the orchestrator.

    On resume the plan is restored from the checkpoint rather than rebuilt,
    so the entry router routes around the supervisor entirely -- the plan
    survives a checkpoint without a second synthesis.
    """
    assert _resume_router(make_state()) == "supervisor"
    assert _resume_router(make_state(resume=True)) == "orchestrator"


def _nodes(generator: HypothesisGenerator) -> set[str]:
    """Return the node names of the generator's currently compiled graph."""
    assert generator._graph is not None
    return set(generator._graph.nodes)


async def test_disabling_literature_review_rebuilds_the_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turning the node off must drop it, not reuse the first topology."""
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
    """Turning the node on must add it back to the executed graph."""
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
    """Compilation is not free, so an unchanged setting must not recompile."""
    stub_mcp_availability(monkeypatch, available=True)
    generator = HypothesisGenerator()

    await generator.prepare_task_state("goal one")
    first = generator._graph
    await generator.prepare_task_state("goal two")
    assert generator._graph is first


async def test_availability_is_probed_once_per_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe is cached, but a registry change invalidates that cache.

    The cached answer decides the graph shape, so it may not outlive the
    tool configuration it was measured against.
    """
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
    """A reloaded registry reaches the state every node reads it from."""
    stub_mcp_availability(monkeypatch, available=True)
    generator = HypothesisGenerator()
    state = await generator.prepare_task_state("goal one")
    first_registry = state["tool_registry"]

    generator.reload_tool_registry(tools_config=None, disable_tools=["pubmed"])
    state = await generator.prepare_task_state("goal two")

    reloaded = generator._tool_registry
    assert reloaded is not None
    # Read the reloaded registry before the identity checks below: comparing
    # it with `is` against an untyped state value re-widens it to optional
    # under mypy 2.x, and the read then reads as a possible None.
    assert "pubmed" not in reloaded.get_enabled_tools()
    assert state["tool_registry"] is not first_registry
    assert state["tool_registry"] is reloaded
