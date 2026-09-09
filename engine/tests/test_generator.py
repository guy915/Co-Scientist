"""Tests for the HypothesisGenerator public entry point.

These cover the parts that are deterministic without a full LLM run:
constructor configuration and env side effects, LangGraph compilation
(node sets for the literature-review and simplified flows), and the
``_prepare_generation`` helper that builds the initial ``WorkflowState``.
The two MCP-availability probes are stubbed so the helper runs offline.
"""

import pytest
from langgraph.graph.state import CompiledStateGraph

from co_scientist.constants import (
    DEFAULT_EVOLUTION_MAX_COUNT,
    DEFAULT_INITIAL_HYPOTHESES_COUNT,
    DEFAULT_MAX_ITERATIONS,
)
from co_scientist.generator import (
    GeneratorOptions,
    HypothesisGenerator,
)

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


# --- _prepare_generation: state building -------------------------------------


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
