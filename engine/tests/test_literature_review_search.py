from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from co_scientist.config import SearchSourceConfig, ToolRegistry, WorkflowConfig
from co_scientist.evidence import search, search_query
from co_scientist.evidence.relevance import _HYBRID_VERSION
from co_scientist.evidence.search_fusion import select_within_budget
from co_scientist.evidence.search_support import SearchConfig
from co_scientist.llm import scoped_campaign_mode
from co_scientist.offline import llm as offline_llm
from tests._mcp import (
    FakeCallToolClient,
    isolate_offline_router,
    make_tool_lookup_registry,
)
from tests._research_fakes import (
    make_search_config,
    make_search_run_ctx,
    make_tool_config,
    make_two_source_workflow,
)
from tests._state import make_state


def _ranked(*ids: str) -> dict[str, dict[str, Any]]:
    return {paper_id: {"title": paper_id} for paper_id in ids}


def _ranked_retracted(
    ids: tuple[str, ...], retracted: set[str]
) -> dict[str, dict[str, Any]]:
    return {
        paper_id: {"title": paper_id, "is_retracted": paper_id in retracted}
        for paper_id in ids
    }


def test_selection_is_pure_score_when_nothing_is_reserved() -> None:
    ranked = _ranked("A", "B", "C", "D")
    source_map = {"A": "pubmed", "B": "pubmed", "C": "corpus", "D": "corpus"}
    sources = [
        SearchSourceConfig(tool="corpus"),
        SearchSourceConfig(tool="pubmed"),
    ]
    assert select_within_budget(ranked, source_map, sources, 2) == ["A", "B"]


def test_reserved_slots_rescue_a_source_that_score_would_truncate() -> None:
    """Metadata-poor corpus papers sort below indexed papers despite matching
    the question."""
    ranked = _ranked("pm1", "pm2", "oa1", "c1", "c2", "c3")
    source_map = {
        "pm1": "pubmed",
        "pm2": "pubmed",
        "oa1": "openalex",
        "c1": "corpus",
        "c2": "corpus",
        "c3": "corpus",
    }
    sources = [
        SearchSourceConfig(tool="corpus", reserved_slots=2),
        SearchSourceConfig(tool="pubmed"),
        SearchSourceConfig(tool="openalex"),
    ]
    selected = select_within_budget(ranked, source_map, sources, 4)
    assert selected == ["c1", "c2", "pm1", "pm2"]


def test_reserved_slots_are_not_padded_when_the_source_returns_fewer() -> None:
    ranked = _ranked("pm1", "pm2", "pm3", "c1")
    source_map = {
        "pm1": "pubmed",
        "pm2": "pubmed",
        "pm3": "pubmed",
        "c1": "corpus",
    }
    sources = [
        SearchSourceConfig(tool="corpus", reserved_slots=2),
        SearchSourceConfig(tool="pubmed"),
    ]
    selected = select_within_budget(ranked, source_map, sources, 3)
    assert selected == ["c1", "pm1", "pm2"]


def test_reserved_slots_never_exceed_the_evidence_budget() -> None:
    ranked = _ranked("c1", "c2", "c3", "pm1")
    source_map = {
        "c1": "corpus",
        "c2": "corpus",
        "c3": "corpus",
        "pm1": "pubmed",
    }
    sources = [
        SearchSourceConfig(tool="corpus", reserved_slots=3),
        SearchSourceConfig(tool="pubmed"),
    ]
    selected = select_within_budget(ranked, source_map, sources, 2)
    assert selected == ["c1", "c2"]
    assert select_within_budget(ranked, source_map, sources, 0) == []


def test_retracted_candidates_never_fill_a_reserved_slot() -> None:
    """A low score sorts a retracted source last but does not exclude it from
    an underfilled pool."""
    ranked = _ranked_retracted(("c1", "c2", "c3"), retracted={"c1", "c2"})
    source_map = {"c1": "corpus", "c2": "corpus", "c3": "corpus"}
    sources = [SearchSourceConfig(tool="corpus", reserved_slots=2)]

    selected = select_within_budget(ranked, source_map, sources, 3)

    assert "c1" not in selected
    assert "c2" not in selected
    assert selected == ["c3"]


def test_retracted_candidates_never_fill_an_underfilled_budget() -> None:
    ranked = _ranked_retracted(("pm1", "pm2"), retracted={"pm2"})
    source_map = {"pm1": "pubmed", "pm2": "pubmed"}
    sources = [SearchSourceConfig(tool="pubmed")]

    selected = select_within_budget(ranked, source_map, sources, 5)

    assert selected == ["pm1"]


def test_a_reservation_short_on_non_retracted_papers_is_not_padded() -> None:
    """Reservations bound one source's candidates, never a quota filled from
    other sources."""
    ranked = _ranked_retracted(("c1", "c2", "pm1"), retracted={"c2"})
    source_map = {"c1": "corpus", "c2": "corpus", "pm1": "pubmed"}
    sources = [
        SearchSourceConfig(tool="corpus", reserved_slots=2),
        SearchSourceConfig(tool="pubmed"),
    ]

    selected = select_within_budget(ranked, source_map, sources, 3)

    assert selected == ["c1", "pm1"]


def test_the_shipped_sources_reserve_no_slots() -> None:
    from co_scientist.config import ToolRegistry

    registry = ToolRegistry(skip_user_config=True)
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None
    reserved = {
        source.tool: source.reserved_slots
        for source in workflow.get_enabled_search_sources()
    }
    assert set(reserved) == {
        "pubmed_fulltext",
        "openalex_search",
        "europepmc_search",
        "web_search",
        "arxiv_search",
        "biorxiv_search",
    }
    assert all(slots == 0 for slots in reserved.values())


def test_enabled_search_sources_track_disabled_tools() -> None:
    from co_scientist.config.registry import ToolRegistry

    registry = ToolRegistry(disabled_tools=["web_search"])
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None

    tools = [s.tool for s in workflow.get_enabled_search_sources()]
    assert "web_search" not in tools
    assert "pubmed_fulltext" in tools


def test_enabled_search_sources_keep_enabled_tools() -> None:
    from co_scientist.config.registry import ToolRegistry

    registry = ToolRegistry()
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None

    tools = [s.tool for s in workflow.get_enabled_search_sources()]
    assert "web_search" in tools


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


@pytest.fixture
def _isolate_offline_router(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_offline_router(monkeypatch)
    offline_llm.install_offline_router()


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


def _multi_source_config(
    registry: Any,
    workflow: WorkflowConfig,
    *,
    source_name: str,
    papers_to_read_count: int,
    search_tool_name: str = "unused",
) -> SearchConfig:
    return make_search_config(
        tool_registry=cast(ToolRegistry, registry),
        workflow=workflow,
        is_multi_source=True,
        search_tool_name=search_tool_name,
        source_name=source_name,
        papers_to_read_count=papers_to_read_count,
    )


async def _collect_multi_source(
    queries: list[str],
    state: Any,
    config: SearchConfig,
    client: Any,
    errors: list[str],
) -> tuple[dict[str, Any], dict[str, str]]:
    return await search._phase2_collect_papers_multi_source(
        queries,
        config,
        make_search_run_ctx(client, errors, run_id=state["run_id"]),
    )


@pytest.mark.usefixtures("_isolate_offline_router")
class TestLiteratureReviewSearchMultiSource:
    def test_build_query_tool_params_with_tool_config_maps_parameters(
        self,
    ) -> None:
        tool_config = make_tool_config(
            parameter_mapping={"query": "q", "recency_years": None}
        )
        params = search_query._build_query_tool_params(
            "cancer", "slug1", "run1", 5, tool_config
        )
        assert params == {
            "q": "cancer",
            "slug": "slug1",
            "max_papers": 5,
            "run_id": "run1",
        }

    def test_bundled_openalex_contract_drops_unsupported_slug(self) -> None:
        tool_config = ToolRegistry().get_tool("openalex_search")
        assert tool_config is not None

        params = search_query._build_query_tool_params(
            "astrocyte lactate", "corpus-slug", "run1", 5, tool_config
        )

        assert params == {
            "query": "astrocyte lactate",
            "max_papers": 5,
            "recency_years": 7,
            "run_id": "run1",
        }

    def test_tag_source_name_tags_dict_entries_only(self) -> None:
        normalized: dict[str, Any] = {"p1": {"title": "A"}, "p2": "not a dict"}
        result: dict[str, Any] = search_query._tag_source_name(
            normalized, "pubmed"
        )
        assert result["p1"]["_source_name"] == "pubmed"
        assert result["p2"] == "not a dict"

    async def test_search_source_for_query_success_tags_results(self) -> None:
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
        self,
        monkeypatch: Any,
    ) -> None:

        async def no_delay(_: float) -> None:
            pass

        monkeypatch.setattr(
            "co_scientist.evidence.search.asyncio.sleep",
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

        assert result == {
            "P1": {"title": "Recovered", "_source_name": "openalex"}
        }
        assert errors == []
        assert len(client.calls) == 2

    async def test_search_source_for_query_error_appends_message_and_empties(
        self,
        monkeypatch: Any,
    ) -> None:

        async def no_delay(_: float) -> None:
            pass

        monkeypatch.setattr(
            "co_scientist.evidence.search.asyncio.sleep",
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
        assert len(client.calls) == search_query._SEARCH_ATTEMPTS

    async def test_search_single_source_missing_tool_config_returns_empty(
        self,
    ) -> None:
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

    async def test_search_single_source_collects_across_queries(self) -> None:
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
        assert results["P1"]["_source_name"] == "academic"
        assert len(client.calls) == 2

    async def test_phase2_collect_papers_multi_source_merges_and_dedupes(
        self,
    ) -> None:
        tool_a = make_tool_config(mcp_tool_name="search_a")
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

    async def test_multi_source_collection_respects_unique_evidence_budget(
        self,
    ) -> None:
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

    async def test_multi_source_hybrid_scores_when_goal_is_set(self) -> None:
        tool_a = make_tool_config(mcp_tool_name="search_a")
        tool_b = make_tool_config(mcp_tool_name="search_b")
        registry = make_tool_lookup_registry({"src_a": tool_a, "src_b": tool_b})
        config = make_search_config(
            tool_registry=cast(ToolRegistry, registry),
            workflow=make_two_source_workflow(4),
            is_multi_source=True,
            search_tool_name="unused",
            source_name="academic",
            papers_to_read_count=2,
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

    async def test_source_error_preserves_healthy_sibling_and_diagnostics(
        self,
    ) -> None:
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
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The registry predates campaign scope; refused sources must be
        filtered before spending retries."""
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
                ["q1"],
                make_state(run_id="run-campaign"),
                config,
                client,
                errors,
            )

        assert [name for name, _ in client.calls] == ["search_pubmed"]
        assert set(metadata) == {"P1"}
        assert errors == []
