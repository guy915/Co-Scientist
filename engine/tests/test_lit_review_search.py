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

from co_scientist.config import (
    SearchSourceConfig,
    ToolConfig,
    ToolRegistry,
    WorkflowConfig,
)
from co_scientist.mcp_client import MCPToolClient
from co_scientist.nodes.literature_review import search
from co_scientist.nodes.literature_review.helpers import SearchConfig
from tests._state import make_state


def _tool_config(
    mcp_tool_name: str = "search_x", **overrides: Any
) -> ToolConfig:
    """Build a minimal ToolConfig for the search tests."""
    return ToolConfig(server="s", mcp_tool_name=mcp_tool_name, **overrides)


class _FakeMCPClient:
    """Minimal ``call_tool``-only stand-in for ``MCPToolClient``.

    Records every call and either returns a fixed response or raises a
    configured error, so success and failure paths can be driven without a
    live MCP server.
    """

    def __init__(
        self, response: Any = None, error: Exception | None = None
    ) -> None:
        """Store the response (or error) every ``call_tool`` invocation uses.

        Args:
            response: Value returned by ``call_tool`` when no error is set.
            error: Exception raised by ``call_tool`` instead of returning.
        """
        self._response = response
        self._error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Record the call and return the response or raise the error."""
        self.calls.append((tool_name, kwargs))
        if self._error is not None:
            raise self._error
        return self._response


class _SequencedMCPClient:
    """Fake MCP client that returns queued responses in call order.

    Used where different calls (e.g. one per query) must yield distinct
    payloads, unlike ``_FakeMCPClient``'s single fixed response.
    """

    def __init__(self, responses: list[Any]) -> None:
        """Store the ordered responses successive ``call_tool`` calls return.

        Args:
            responses: One response per expected call, consumed in order.
        """
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Record the call and pop the next queued response."""
        self.calls.append((tool_name, kwargs))
        return self._responses.pop(0)


class _StubRegistry:
    """Minimal stand-in for ``ToolRegistry`` exposing only ``get_tool``."""

    def __init__(self, tools: dict[str, ToolConfig]) -> None:
        """Store the tool-id -> ToolConfig map ``get_tool`` resolves."""
        self._tools = tools

    def get_tool(self, tool_id: str) -> ToolConfig | None:
        """Resolve a tool id to its configured ToolConfig, or None."""
        return self._tools.get(tool_id)


# =============================================================================
# _build_query_tool_params
# =============================================================================


def test_build_query_tool_params_with_tool_config_maps_parameters() -> None:
    """A tool config maps canonical params and drops null-mapped entries."""
    tool_config = _tool_config(
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
    tool_config = _tool_config()
    client = _FakeMCPClient(response={"P1": {"title": "T1"}})
    errors: list[str] = []

    result = await search._search_source_for_query(
        "query",
        "slug",
        "run1",
        tool_config,
        "pubmed",
        3,
        cast(MCPToolClient, client),
        errors,
    )

    assert result == {"P1": {"title": "T1", "_source_name": "pubmed"}}
    assert errors == []
    assert client.calls[0][0] == "search_x"


async def test_search_source_for_query_error_appends_message_and_empties() -> (
    None
):
    """A raised exception is swallowed, described, and appended to errors."""
    tool_config = _tool_config()
    client = _FakeMCPClient(error=ConnectionError("boom"))
    errors: list[str] = []

    result = await search._search_source_for_query(
        "q",
        "slug",
        "run1",
        tool_config,
        "pubmed",
        3,
        cast(MCPToolClient, client),
        errors,
    )

    assert result == {}
    assert errors == ["pubmed: ConnectionError: boom"]


# =============================================================================
# _search_single_source
# =============================================================================


async def test_search_single_source_missing_tool_config_returns_empty() -> None:
    """An unresolvable source tool logs and returns an empty result set."""
    registry = _StubRegistry({})
    client = _FakeMCPClient()
    source = SearchSourceConfig(tool="missing_tool")

    result = await search._search_single_source(
        source,
        ["q1"],
        "slug",
        "run1",
        cast(ToolRegistry, registry),
        cast(MCPToolClient, client),
    )

    assert result == ("missing_tool", {})
    assert client.calls == []


async def test_search_single_source_collects_across_queries() -> None:
    """Every query for a resolved source is searched and merged together."""
    tool_config = _tool_config(mcp_tool_name="search_pubmed")
    registry = _StubRegistry({"pubmed_ft": tool_config})
    client = _FakeMCPClient(response={"P1": {"title": "T1"}})
    source = SearchSourceConfig(tool="pubmed_ft", papers_per_query=2)

    tool_id, results = await search._search_single_source(
        source,
        ["q1", "q2"],
        "slug",
        "run1",
        cast(ToolRegistry, registry),
        cast(MCPToolClient, client),
    )

    assert tool_id == "pubmed_ft"
    assert results["P1"]["title"] == "T1"
    # extract_source_name falls back to ToolConfig.source_type by default.
    assert results["P1"]["_source_name"] == "academic"
    assert len(client.calls) == 2


# =============================================================================
# _search_all_sources / _phase2_collect_papers_multi_source
# =============================================================================


async def test_phase2_collect_papers_multi_source_merges_and_dedupes() -> None:
    """Multi-source phase 2 collects from all sources and dedupes by title.

    One of the two configured sources has no resolvable tool config (hitting
    ``_search_single_source``'s not-found branch); the other returns two
    queries' worth of papers sharing a title, which ``merge_search_results``
    collapses to a single entry.
    """
    tool_a = _tool_config(mcp_tool_name="search_a")
    registry = _StubRegistry({"src_a": tool_a})  # src_b is unresolvable.
    workflow = WorkflowConfig(
        search_sources=[
            SearchSourceConfig(tool="src_a", papers_per_query=2),
            SearchSourceConfig(tool="src_b", papers_per_query=2),
        ],
        deduplicate_across_sources=True,
    )
    config = SearchConfig(
        tool_registry=cast(ToolRegistry, registry),
        workflow=workflow,
        is_multi_source=True,
        search_tool_name="pubmed_search_with_fulltext",
        search_tool_config=None,
        source_name="pubmed",
        papers_to_read_count=10,
        is_dev_mode=False,
    )
    client = _SequencedMCPClient(
        [
            {"P1": {"title": "Same Title"}},
            {"P2": {"title": "Same Title"}},
        ]
    )
    state = make_state(run_id="run-multi")
    errors: list[str] = []

    (
        all_paper_metadata,
        paper_source_map,
    ) = await search._phase2_collect_papers_multi_source(
        ["q1", "q2"],
        "slug",
        state,
        config,
        cast(MCPToolClient, client),
        errors,
    )

    assert set(all_paper_metadata) == {"P1"}
    assert paper_source_map == {"P1": "src_a"}
    assert len(client.calls) == 2
