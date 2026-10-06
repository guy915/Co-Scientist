from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from co_scientist.agents.generation.literature_review import (
    literature_review_node,
)
from co_scientist.config import SearchSourceConfig, ToolRegistry, WorkflowConfig
from co_scientist.evidence import search, search_query
from co_scientist.llm import scoped_campaign_mode
from tests._mcp import make_tool_lookup_registry
from tests._research_fakes import (
    _stub_node,
    make_search_config,
    make_search_run_ctx,
    make_tool_config,
    make_two_source_workflow,
)
from tests._state import make_state


@pytest.mark.parametrize(
    ("ids", "reserved", "budget", "retracted", "expected"),
    [
        (("pm1", "pm2", "c1", "c2"), 0, 2, set(), ["pm1", "pm2"]),
        (
            ("pm1", "pm2", "oa1", "c1", "c2", "c3"),
            2,
            4,
            set(),
            ["c1", "c2", "pm1", "pm2"],
        ),
        (("pm1", "pm2", "pm3", "c1"), 2, 3, set(), ["c1", "pm1", "pm2"]),
        (("c1", "c2", "c3", "pm1"), 3, 2, set(), ["c1", "c2"]),
        (("c1", "c2", "c3"), 2, 3, {"c1", "c2"}, ["c3"]),
        (("pm1", "pm2"), 0, 5, {"pm2"}, ["pm1"]),
        (("c1", "pm1"), 1, -1, set(), []),
        (("c1", "c2", "pm1"), 2, 3, {"c2"}, ["c1", "pm1"]),
    ],
    ids=[
        "unreserved",
        "reserved",
        "underfilled-source",
        "cap",
        "retracted-reservation",
        "retracted-underfilled",
        "nonpositive-budget",
        "no-padding",
    ],
)
async def test_review_respects_reservations_and_excludes_retracted_evidence(
    monkeypatch: pytest.MonkeyPatch,
    ids: tuple[str, ...],
    reserved: int,
    budget: int,
    retracted: set[str],
    expected: list[str],
) -> None:
    ranked = {
        paper_id: {"title": paper_id, "is_retracted": paper_id in retracted}
        for paper_id in ids
    }
    source_map = {
        paper_id: "corpus" if paper_id.startswith("c") else "pubmed"
        for paper_id in ids
    }
    _stub_node(monkeypatch, server_available=True, search_payload=ranked)
    monkeypatch.setattr(
        search,
        "merge_search_results",
        lambda *args, **kwargs: (ranked, source_map),
    )
    registry = ToolRegistry(skip_user_config=True)
    registry.config.workflows = {
        "literature_review": WorkflowConfig(
            search_sources=[
                SearchSourceConfig(tool="corpus", reserved_slots=reserved),
                SearchSourceConfig(tool="pubmed"),
            ]
        )
    }
    registry.config.tools = {
        "tools": {name: make_tool_config(name) for name in ("corpus", "pubmed")}
    }
    result = await literature_review_node(
        make_state(
            research_goal="",
            tool_registry=registry,
            literature_review_papers_count=budget,
        )
    )
    assert [article.source_id for article in result["articles"]] == expected


class _BarrierMCPClient:
    """A barrier proves overlap without timing assumptions. Python 3.10
    lacks asyncio.Barrier, so this fixture implements its own."""

    def __init__(self, parties: int, response: Any) -> None:
        self._parties = parties
        self._released = asyncio.Event()
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.max_in_flight = 0
        self._in_flight = 0

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        self.calls.append((tool_name, kwargs))
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        if self._in_flight >= self._parties:
            self._released.set()
        await self._released.wait()
        self._in_flight -= 1
        return self.response


async def test_queries_for_one_source_run_concurrently() -> None:
    tool_config = make_tool_config(mcp_tool_name="search_pubmed")
    registry = make_tool_lookup_registry({"pubmed_ft": tool_config})
    client = _BarrierMCPClient(parties=3, response={"P1": {"title": "T1"}})
    source = SearchSourceConfig(tool="pubmed_ft", papers_per_query=2)

    _, results = await asyncio.wait_for(
        search._search_single_source(
            source,
            ["q1", "q2", "q3"],
            make_search_run_ctx(client, []),
            cast(ToolRegistry, registry),
        ),
        timeout=5,
    )

    assert client.max_in_flight == 3
    assert len(client.calls) == 3
    assert results["P1"]["title"] == "T1"


async def test_sources_still_overlap_with_concurrent_queries() -> None:
    registry = make_tool_lookup_registry(
        {
            "src_a": make_tool_config(mcp_tool_name="search_a"),
            "src_b": make_tool_config(mcp_tool_name="search_b"),
        }
    )
    client = _BarrierMCPClient(parties=4, response={"P1": {"title": "T1"}})
    workflow = make_two_source_workflow(2)

    results = await asyncio.wait_for(
        search._search_all_sources(
            workflow.search_sources,
            ["q1", "q2"],
            make_search_run_ctx(client, []),
            cast(ToolRegistry, registry),
        ),
        timeout=5,
    )

    assert client.max_in_flight == 4
    assert [tool for tool, _ in results] == ["src_a", "src_b"]


class _PerQueryMCPClient:
    """Concurrent calls and retries cannot map outcomes from one flat
    response queue."""

    def __init__(self, outcomes: dict[str, Any]) -> None:
        self._outcomes = outcomes
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        self.calls.append((tool_name, kwargs))
        outcome = self._outcomes[str(kwargs["query"])]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def test_one_failed_query_does_not_discard_its_siblings() -> None:
    tool_config = make_tool_config(mcp_tool_name="search_pubmed")
    registry = make_tool_lookup_registry({"pubmed_ft": tool_config})
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
        make_search_run_ctx(client, errors),
        cast(ToolRegistry, registry),
    )

    assert set(results) == {"P1", "P3"}
    assert errors == ["academic: ConnectionError: boom"]


async def test_duplicate_papers_keep_the_last_query_s_metadata() -> None:
    """Merge order follows queries, so completion timing cannot change
    selected metadata."""
    tool_config = make_tool_config(mcp_tool_name="search_pubmed")
    registry = make_tool_lookup_registry({"pubmed_ft": tool_config})
    client = _OutOfOrderMCPClient(
        [
            {"P1": {"title": "From q1"}},
            {"P1": {"title": "From q2"}},
        ]
    )

    _, results = await search._search_single_source(
        SearchSourceConfig(tool="pubmed_ft", papers_per_query=2),
        ["q1", "q2"],
        make_search_run_ctx(client, []),
        cast(ToolRegistry, registry),
    )

    assert results["P1"]["title"] == "From q2"


class _OutOfOrderMCPClient:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self._gate = asyncio.Event()
        self._index = 0
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        self.calls.append((tool_name, kwargs))
        index = self._index
        self._index += 1
        if index == 0:
            await self._gate.wait()
        else:
            self._gate.set()
        return self._responses[index]


class _SequencedMCPClient:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        self.calls.append((tool_name, kwargs))
        outcome = self._responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def _collect_multi_source(
    registry: Any,
    client: Any,
    errors: list[str],
    *,
    papers_per_query: int,
    semantic: bool = True,
) -> tuple[dict[str, Any], dict[str, str]]:
    config = make_search_config(
        tool_registry=cast(ToolRegistry, registry),
        workflow=make_two_source_workflow(papers_per_query),
        is_multi_source=True,
        search_tool_name="unused",
        source_name="mixed",
        papers_to_read_count=10,
    )
    config.semantic_relevance_enabled = semantic
    return await search._phase2_collect_papers_multi_source(
        ["q1"], config, make_search_run_ctx(client, errors, run_id="run-1")
    )


@pytest.mark.parametrize(
    ("tool_config", "expected"),
    [
        (
            make_tool_config(
                parameter_mapping={"query": "q", "recency_years": None}
            ),
            {
                "q": "cancer",
                "slug": "slug1",
                "max_papers": 5,
                "run_id": "run1",
            },
        ),
        # The bundled OpenAlex contract has no slug parameter.
        (
            ToolRegistry().get_tool("openalex_search"),
            {
                "query": "cancer",
                "max_papers": 5,
                "recency_years": 7,
                "run_id": "run1",
            },
        ),
    ],
    ids=["custom-mapping", "bundled-openalex"],
)
def test_the_configured_contract_decides_the_search_parameters(
    tool_config: Any, expected: dict[str, Any]
) -> None:
    assert tool_config is not None

    params = search_query._build_query_tool_params(
        "cancer", "slug1", "run1", 5, tool_config
    )

    assert params == expected


async def test_a_failing_source_keeps_its_healthy_sibling_and_diagnostics() -> (
    None
):
    registry = make_tool_lookup_registry(
        {
            "src_a": make_tool_config(mcp_tool_name="search_europepmc"),
            "src_b": make_tool_config(mcp_tool_name="search_pubmed"),
        }
    )

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
        registry, Client(), errors, papers_per_query=1, semantic=False
    )

    assert set(papers) == {"P1"}
    assert sources == {"P1": "src_b"}
    assert len(errors) == 1
    assert "search_europepmc" in errors[0] and "Europe PMC" in errors[0]
    assert "HTTP 503" in errors[0]


async def test_campaign_scope_skips_a_source_its_policy_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registry predates campaign scope; refused sources must be filtered
    before spending retries."""
    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)
    registry = make_tool_lookup_registry(
        {
            "src_a": make_tool_config(mcp_tool_name="search_pubmed"),
            "src_b": make_tool_config(mcp_tool_name="search_web"),
        }
    )
    client = _SequencedMCPClient([{"P1": {"title": "Only PubMed"}}])
    errors: list[str] = []

    with scoped_campaign_mode(True):
        metadata, _ = await _collect_multi_source(
            registry, client, errors, papers_per_query=2, semantic=False
        )

    assert [name for name, _ in client.calls] == ["search_pubmed"]
    assert set(metadata) == {"P1"}
    assert errors == []
