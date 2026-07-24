"""Tests for concurrent query execution in literature review phase 2.

A source's queries are independent round-trips to the same tool, so they
run concurrently rather than one at a time. These tests hold that property
directly: the fakes below block until a set number of calls are in flight,
so a sequential implementation deadlocks and fails the timeout instead of
passing on a fast machine.

They also pin the two properties concurrency could quietly break -- that a
failed query cannot take its siblings down with it, and that merging still
follows query order rather than whichever index answered first.

External seams stubbed: only the MCP client's ``call_tool`` and a minimal
``ToolRegistry`` stub; no network, LLM, or disk I/O anywhere in this module.
"""

import asyncio
from typing import Any, cast

from co_scientist.agents.generation.literature_review import search
from co_scientist.config import (
    SearchSourceConfig,
    ToolConfig,
    ToolRegistry,
    WorkflowConfig,
)
from co_scientist.mcp_client import MCPToolClient
from tests._mcp import make_tool_lookup_registry


def _tool_config(
    mcp_tool_name: str = "search_x", **overrides: Any
) -> ToolConfig:
    """Build a minimal ToolConfig for the search tests."""
    return ToolConfig(server="s", mcp_tool_name=mcp_tool_name, **overrides)


def _run_ctx(
    client: Any, errors: list[str], run_id: str = "run1"
) -> search._SearchRunContext:
    """A run context over the shared ``"slug"`` slug for search calls."""
    return search._SearchRunContext(
        slug="slug",
        run_id=run_id,
        mcp_client=cast(MCPToolClient, client),
        errors=errors,
    )


def _two_source_workflow(papers_per_query: int) -> WorkflowConfig:
    """A cross-source-deduped workflow with src_a and src_b sources."""
    return WorkflowConfig(
        search_sources=[
            SearchSourceConfig(tool="src_a", papers_per_query=papers_per_query),
            SearchSourceConfig(tool="src_b", papers_per_query=papers_per_query),
        ],
        deduplicate_across_sources=True,
    )


class _BarrierMCPClient:
    """Fake client that blocks until a set number of calls are in flight.

    Lets a test assert real overlap rather than infer it from timing: if the
    queries were awaited one at a time, the first would wait forever for
    siblings that have not been issued, and the test would hang rather than
    pass by accident on a fast machine.
    """

    def __init__(self, parties: int, response: Any) -> None:
        """Arm a barrier for ``parties`` concurrent calls.

        Hand-rolled rather than ``asyncio.Barrier``: the engine supports
        Python 3.10, where that class does not exist.

        Args:
            parties: How many calls must arrive before any may proceed.
            response: Payload every call returns once released.
        """
        self._parties = parties
        self._released = asyncio.Event()
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.max_in_flight = 0
        self._in_flight = 0

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Record the call, wait for its siblings, then respond."""
        self.calls.append((tool_name, kwargs))
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        if self._in_flight >= self._parties:
            self._released.set()
        await self._released.wait()
        self._in_flight -= 1
        return self.response


async def test_queries_for_one_source_run_concurrently() -> None:
    """A source's queries overlap instead of costing their sum.

    The barrier only releases once all three calls are in flight, so this
    test cannot pass if the queries are awaited sequentially.
    """
    tool_config = _tool_config(mcp_tool_name="search_pubmed")
    registry = make_tool_lookup_registry({"pubmed_ft": tool_config})
    client = _BarrierMCPClient(parties=3, response={"P1": {"title": "T1"}})
    source = SearchSourceConfig(tool="pubmed_ft", papers_per_query=2)

    _, results = await asyncio.wait_for(
        search._search_single_source(
            source,
            ["q1", "q2", "q3"],
            _run_ctx(client, []),
            cast(ToolRegistry, registry),
        ),
        timeout=5,
    )

    assert client.max_in_flight == 3
    assert len(client.calls) == 3
    assert results["P1"]["title"] == "T1"


async def test_sources_still_overlap_with_concurrent_queries() -> None:
    """Cross-source parallelism survives the within-source change."""
    registry = make_tool_lookup_registry(
        {
            "src_a": _tool_config(mcp_tool_name="search_a"),
            "src_b": _tool_config(mcp_tool_name="search_b"),
        }
    )
    # Two sources x two queries must all be in flight together.
    client = _BarrierMCPClient(parties=4, response={"P1": {"title": "T1"}})
    workflow = _two_source_workflow(2)

    results = await asyncio.wait_for(
        search._search_all_sources(
            workflow.search_sources,
            ["q1", "q2"],
            _run_ctx(client, []),
            cast(ToolRegistry, registry),
        ),
        timeout=5,
    )

    assert client.max_in_flight == 4
    assert [tool for tool, _ in results] == ["src_a", "src_b"]


class _PerQueryMCPClient:
    """Fake client that answers by query text rather than by call order.

    Concurrent queries interleave their calls and retries, so a fake that
    pops a flat response list no longer maps outcomes to the query that
    asked for them.
    """

    def __init__(self, outcomes: dict[str, Any]) -> None:
        """Map each query string to the response or exception it gets."""
        self._outcomes = outcomes
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Return or raise the outcome registered for this call's query."""
        self.calls.append((tool_name, kwargs))
        outcome = self._outcomes[str(kwargs["query"])]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def test_one_failed_query_does_not_discard_its_siblings() -> None:
    """A broken query is isolated; the rest of the source still lands."""
    tool_config = _tool_config(mcp_tool_name="search_pubmed")
    registry = make_tool_lookup_registry({"pubmed_ft": tool_config})
    # The middle query fails every attempt; the others succeed.
    client = _PerQueryMCPClient(
        {
            "q1": {"P1": {"title": "First"}},
            "q2": ConnectionError("boom"),
            "q3": {"P3": {"title": "Third"}},
        }
    )
    errors: list[str] = []

    _, results = await search._search_single_source(
        SearchSourceConfig(tool="pubmed_ft", papers_per_query=2),
        ["q1", "q2", "q3"],
        _run_ctx(client, errors),
        cast(ToolRegistry, registry),
    )

    assert set(results) == {"P1", "P3"}
    assert errors == ["academic: ConnectionError: boom"]


async def test_duplicate_papers_keep_the_last_query_s_metadata() -> None:
    """Merging follows query order, not completion order.

    Concurrency must not make selection depend on which index answered
    first: the same paper seen by several queries has to resolve the same
    way every run.
    """
    tool_config = _tool_config(mcp_tool_name="search_pubmed")
    registry = make_tool_lookup_registry({"pubmed_ft": tool_config})
    # The later query answers first, but must still win the merge, exactly
    # as it did when the loop awaited them in order.
    client = _OutOfOrderMCPClient(
        [
            {"P1": {"title": "From q1"}},
            {"P1": {"title": "From q2"}},
        ]
    )

    _, results = await search._search_single_source(
        SearchSourceConfig(tool="pubmed_ft", papers_per_query=2),
        ["q1", "q2"],
        _run_ctx(client, []),
        cast(ToolRegistry, registry),
    )

    assert results["P1"]["title"] == "From q2"


class _OutOfOrderMCPClient:
    """Fake client that answers later calls before earlier ones.

    Forces the merge to depend on query order rather than on the order the
    sources happened to reply in.
    """

    def __init__(self, responses: list[Any]) -> None:
        """Queue one response per call, answered in reverse arrival order."""
        self._responses = list(responses)
        self._gate = asyncio.Event()
        self._index = 0
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Hold the first call until the last has been issued."""
        self.calls.append((tool_name, kwargs))
        index = self._index
        self._index += 1
        if index == 0:
            await self._gate.wait()
        else:
            self._gate.set()
        return self._responses[index]
