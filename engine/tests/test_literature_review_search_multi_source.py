"""Tests for literature review phase 2 paper collection (search.py).

Covers the private helpers ``_build_query_tool_params``, ``_tag_source_name``,
``_search_source_for_query`` (success and swallowed-error paths),
``_search_single_source`` (unresolvable and resolvable tool paths), and the
multi-source orchestration (``_search_all_sources`` /
``_phase2_collect_papers_multi_source``) that the existing
``test_literature_review_node`` happy-path tests never reach, since those
always run with ``tool_registry=None`` (the legacy single-source path).

External seams stubbed: only the MCP client's ``call_tool`` (an in-memory fake
recording calls) and a minimal ``ToolRegistry`` stub exposing ``get_tool``; no
network, LLM, or disk I/O anywhere in this module.
"""

from typing import Any, cast

import pytest

from co_scientist import offline_llm
from co_scientist.agents.generation.literature_review import search
from co_scientist.agents.generation.literature_review.helpers import (
    SearchConfig,
)
from co_scientist.agents.generation.literature_review.relevance import (
    _HYBRID_VERSION,
)
from co_scientist.config import (
    SearchSourceConfig,
    ToolRegistry,
    WorkflowConfig,
)
from co_scientist.llm import scoped_campaign_mode
from tests._mcp import FakeCallToolClient, make_tool_lookup_registry
from tests._offline_helpers import isolate_offline_router
from tests._retrieval_config import make_tool_config
from tests._search_fixtures import (
    make_search_run_ctx,
    make_two_source_workflow,
)
from tests._state import make_state


@pytest.fixture(autouse=True)
def _isolate_offline_router(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_offline_router(monkeypatch)
    offline_llm.install_offline_router()


class _SequencedMCPClient:
    """Fake MCP client that returns queued responses in call order.

    Used where different calls (e.g. one per query) must yield distinct
    payloads, unlike ``FakeCallToolClient``'s single fixed response.
    """

    def __init__(self, responses: list[Any]) -> None:
        """Store the ordered responses successive ``call_tool`` calls return.

        Args:
            responses: One response per expected call, consumed in order.
        """
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Record the call and return or raise the next queued outcome."""
        self.calls.append((tool_name, kwargs))
        outcome = self._responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


# =============================================================================
# _build_query_tool_params
# =============================================================================


def test_build_query_tool_params_with_tool_config_maps_parameters() -> None:
    """A tool config maps canonical params and drops null-mapped entries."""
    tool_config = make_tool_config(
        parameter_mapping={"query": "q", "recency_years": None}
    )
    params = search._build_query_tool_params(
        "cancer", "slug1", "run1", 5, tool_config
    )
    assert params == {
        "q": "cancer",
        "slug": "slug1",
        "max_papers": 5,
        "run_id": "run1",
    }


def test_bundled_openalex_contract_drops_unsupported_slug() -> None:
    """Bundled OpenAlex calls contain only parameters its MCP tool accepts."""
    tool_config = ToolRegistry().get_tool("openalex_search")
    assert tool_config is not None

    params = search._build_query_tool_params(
        "astrocyte lactate", "corpus-slug", "run1", 5, tool_config
    )

    assert params == {
        "query": "astrocyte lactate",
        "max_papers": 5,
        "recency_years": 7,
        "run_id": "run1",
    }


# =============================================================================
# _tag_source_name
# =============================================================================


def test_tag_source_name_tags_dict_entries_only() -> None:
    """Only dict-valued entries get the ``_source_name`` key added in place."""
    normalized: dict[str, Any] = {"p1": {"title": "A"}, "p2": "not a dict"}
    result: dict[str, Any] = search._tag_source_name(normalized, "pubmed")
    assert result["p1"]["_source_name"] == "pubmed"
    assert result["p2"] == "not a dict"


# =============================================================================
# _search_source_for_query
# =============================================================================


async def test_search_source_for_query_success_tags_results() -> None:
    """A successful call normalizes and tags the source name onto results."""
    tool_config = make_tool_config()
    client = FakeCallToolClient(response={"P1": {"title": "T1"}})
    errors: list[str] = []

    result = await search._search_source_for_query(
        "query",
        make_search_run_ctx(client, errors),
        tool_config,
        "pubmed",
        3,
    )

    assert result == {"P1": {"title": "T1", "_source_name": "pubmed"}}
    assert errors == []
    assert client.calls[0][0] == "search_x"


async def test_search_source_for_query_retries_malformed_transport_result(
    monkeypatch: Any,
) -> None:
    """A transient non-JSON response is retried before losing the source."""

    async def no_delay(_: float) -> None:
        """Skip the production retry delay in this deterministic test."""

    monkeypatch.setattr(
        "co_scientist.agents.generation.literature_review.search.asyncio.sleep",
        no_delay,
    )
    tool_config = make_tool_config()
    client = _SequencedMCPClient(
        ["429 Too Many Requests", {"P1": {"title": "Recovered"}}]
    )
    errors: list[str] = []

    result = await search._search_source_for_query(
        "query",
        make_search_run_ctx(client, errors),
        tool_config,
        "openalex",
        3,
    )

    assert result == {"P1": {"title": "Recovered", "_source_name": "openalex"}}
    assert errors == []
    assert len(client.calls) == 2


async def test_search_source_for_query_error_appends_message_and_empties(
    monkeypatch: Any,
) -> None:
    """A raised exception is swallowed, described, and appended to errors."""

    async def no_delay(_: float) -> None:
        """Skip the production backoff in this deterministic test."""

    # This test is about the outcome of exhausting the retry budget, not
    # about how long exhausting it takes.
    monkeypatch.setattr(
        "co_scientist.agents.generation.literature_review.search.asyncio.sleep",
        no_delay,
    )
    tool_config = make_tool_config()
    client = FakeCallToolClient(error=ConnectionError("boom"))
    errors: list[str] = []

    result = await search._search_source_for_query(
        "q",
        make_search_run_ctx(client, errors),
        tool_config,
        "pubmed",
        3,
    )

    assert result == {}
    assert errors == ["pubmed: ConnectionError: boom"]
    # Read from the constant: the retry budget is tuned against upstream
    # behavior, and a hardcoded copy here turns tuning it into a test break.
    assert len(client.calls) == search._SEARCH_ATTEMPTS


# =============================================================================
# _search_single_source
# =============================================================================


async def test_search_single_source_missing_tool_config_returns_empty() -> None:
    """An unresolvable source tool logs and returns an empty result set."""
    registry = make_tool_lookup_registry({})
    client = FakeCallToolClient()
    source = SearchSourceConfig(tool="missing_tool")

    result = await search._search_single_source(
        source,
        ["q1"],
        make_search_run_ctx(client, []),
        cast(ToolRegistry, registry),
    )

    assert result == ("missing_tool", {})
    assert client.calls == []


async def test_search_single_source_collects_across_queries() -> None:
    """Every query for a resolved source is searched and merged together."""
    tool_config = make_tool_config(mcp_tool_name="search_pubmed")
    registry = make_tool_lookup_registry({"pubmed_ft": tool_config})
    client = FakeCallToolClient(response={"P1": {"title": "T1"}})
    source = SearchSourceConfig(tool="pubmed_ft", papers_per_query=2)

    tool_id, results = await search._search_single_source(
        source,
        ["q1", "q2"],
        make_search_run_ctx(client, []),
        cast(ToolRegistry, registry),
    )

    assert tool_id == "pubmed_ft"
    assert results["P1"]["title"] == "T1"
    # extract_source_name falls back to ToolConfig.source_type by default.
    assert results["P1"]["_source_name"] == "academic"
    assert len(client.calls) == 2


# =============================================================================
# _search_all_sources / _phase2_collect_papers_multi_source
# =============================================================================


def _multi_source_config(
    registry: Any,
    workflow: WorkflowConfig,
    *,
    source_name: str,
    papers_to_read_count: int,
    search_tool_name: str = "unused",
) -> SearchConfig:
    """A multi-source SearchConfig over the given registry and workflow."""
    return SearchConfig(
        tool_registry=cast(ToolRegistry, registry),
        workflow=workflow,
        is_multi_source=True,
        search_tool_name=search_tool_name,
        search_tool_config=None,
        source_name=source_name,
        papers_to_read_count=papers_to_read_count,
        is_dev_mode=False,
    )


async def _collect_multi_source(
    queries: list[str],
    state: Any,
    config: SearchConfig,
    client: Any,
    errors: list[str],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Run multi-source phase 2 collection with the shared ``"slug"`` slug."""
    return await search._phase2_collect_papers_multi_source(
        queries,
        config,
        make_search_run_ctx(client, errors, run_id=state["run_id"]),
    )


async def test_phase2_collect_papers_multi_source_merges_and_dedupes() -> None:
    """Multi-source phase 2 collects from all sources and dedupes by title.

    One of the two configured sources has no resolvable tool config (hitting
    ``_search_single_source``'s not-found branch); the other returns two
    queries' worth of papers sharing a title, which ``merge_search_results``
    collapses to a single entry.
    """
    tool_a = make_tool_config(mcp_tool_name="search_a")
    # src_b is unresolvable.
    registry = make_tool_lookup_registry({"src_a": tool_a})
    config = _multi_source_config(
        registry,
        make_two_source_workflow(2),
        source_name="pubmed",
        papers_to_read_count=10,
        search_tool_name="pubmed_search_with_fulltext",
    )
    client = _SequencedMCPClient(
        [
            {"P1": {"title": "Same Title"}},
            {"P2": {"title": "Same Title"}},
        ]
    )
    state = make_state(run_id="run-multi")
    errors: list[str] = []

    all_paper_metadata, paper_source_map = await _collect_multi_source(
        ["q1", "q2"], state, config, client, errors
    )

    assert set(all_paper_metadata) == {"P1"}
    assert paper_source_map == {"P1": "src_a"}
    assert len(client.calls) == 2


async def test_multi_source_collection_respects_unique_evidence_budget() -> (
    None
):
    """Ranked multi-source results are capped to the configured corpus size."""
    tool_a = make_tool_config(mcp_tool_name="search_a")
    tool_b = make_tool_config(mcp_tool_name="search_b")
    registry = make_tool_lookup_registry({"src_a": tool_a, "src_b": tool_b})
    config = _multi_source_config(
        registry,
        make_two_source_workflow(4),
        source_name="academic",
        papers_to_read_count=2,
    )
    client = _SequencedMCPClient(
        [
            {
                "A": {"title": "A", "year": 2025},
                "B": {"title": "B", "year": 2024},
            },
            {
                "C": {"title": "C", "year": 2023},
                "D": {"title": "D", "year": 2022},
            },
        ]
    )

    metadata, source_map = await _collect_multi_source(
        ["query"], make_state(run_id="run-budget"), config, client, []
    )

    assert len(metadata) == 2
    assert set(metadata) == set(source_map)


async def test_multi_source_hybrid_scores_when_goal_is_set() -> None:
    """A configured research goal runs the semantic pass before budgeting.

    Every selected paper carries a normalized hybrid score and its
    provenance, and reserved-slot selection still runs unmodified on top
    of the re-ranked pool.
    """
    tool_a = make_tool_config(mcp_tool_name="search_a")
    tool_b = make_tool_config(mcp_tool_name="search_b")
    registry = make_tool_lookup_registry({"src_a": tool_a, "src_b": tool_b})
    config = SearchConfig(
        tool_registry=cast(ToolRegistry, registry),
        workflow=make_two_source_workflow(4),
        is_multi_source=True,
        search_tool_name="unused",
        search_tool_config=None,
        source_name="academic",
        papers_to_read_count=2,
        is_dev_mode=False,
        research_goal="a research goal",
        model_name=offline_llm.DEFAULT_OFFLINE_MODEL,
    )
    client = _SequencedMCPClient(
        [
            {
                "A": {"title": "A", "year": 2025},
                "B": {"title": "B", "year": 2024},
            },
            {
                "C": {"title": "C", "year": 2023},
                "D": {"title": "D", "year": 2022},
            },
        ]
    )

    metadata, _ = await _collect_multi_source(
        ["query"], make_state(run_id="run-hybrid"), config, client, []
    )

    assert len(metadata) == 2
    for item in metadata.values():
        assert 0.0 <= item["retrieval_score"] <= 1.0
        assert item["retriever_version"] == _HYBRID_VERSION


async def test_source_error_preserves_healthy_sibling_and_diagnostics() -> None:
    registry = make_tool_lookup_registry(
        {
            "src_a": make_tool_config(mcp_tool_name="search_europepmc"),
            "src_b": make_tool_config(mcp_tool_name="search_pubmed"),
        }
    )
    config = _multi_source_config(
        registry,
        make_two_source_workflow(1),
        source_name="mixed",
        papers_to_read_count=2,
    )
    config.semantic_relevance_enabled = False

    class Client:
        async def call_tool(self, name: str, **_: Any) -> Any:
            if name == "search_europepmc":
                return (
                    "Error calling tool 'search_europepmc': "
                    "Europe PMC unavailable: HTTP 503"
                )
            return {"P1": {"title": "Healthy source paper"}}

    errors: list[str] = []
    papers, sources = await _collect_multi_source(
        ["q"], make_state(), config, Client(), errors
    )
    assert set(papers) == {"P1"}
    assert sources == {"P1": "src_b"}
    assert len(errors) == 1
    assert "search_europepmc" in errors[0] and "Europe PMC" in errors[0]
    assert "HTTP 503" in errors[0]


async def test_campaign_scope_skips_a_source_its_policy_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source the campaign MCP policy refuses is never called.

    The registry is built before the campaign scope is known, so web search
    stays enabled there; every call to it was refused, retried four times,
    and logged at ERROR on each literature pass.
    """
    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)
    registry = make_tool_lookup_registry(
        {
            "src_a": make_tool_config(mcp_tool_name="search_pubmed"),
            "src_b": make_tool_config(mcp_tool_name="search_web"),
        }
    )
    config = _multi_source_config(
        registry,
        make_two_source_workflow(2),
        source_name="pubmed",
        papers_to_read_count=10,
    )
    client = _SequencedMCPClient([{"P1": {"title": "Only PubMed"}}])
    errors: list[str] = []

    with scoped_campaign_mode(True):
        metadata, _ = await _collect_multi_source(
            ["q1"], make_state(run_id="run-campaign"), config, client, errors
        )

    assert [name for name, _ in client.calls] == ["search_pubmed"]
    assert set(metadata) == {"P1"}
    assert errors == []
