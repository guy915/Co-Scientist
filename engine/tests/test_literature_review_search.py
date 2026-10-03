"""Offline contracts for literature review search."""

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
    make_search_run_ctx,
    make_tool_config,
    make_two_source_workflow,
)
from tests._state import make_state


def _ranked(*ids: str) -> dict[str, dict[str, Any]]:
    """Papers in ranked (best-first) order, as merge_search_results returns."""
    return {paper_id: {"title": paper_id} for paper_id in ids}


def _ranked_retracted(
    ids: tuple[str, ...], retracted: set[str]
) -> dict[str, dict[str, Any]]:
    """Ranked papers, marking each id in ``retracted`` as retracted.

    Mirrors what a source's own metadata carries -- ``is_retracted`` is the
    flat shape OpenAlex reports; the multi-shape detector covers the rest.
    """
    return {
        paper_id: {"title": paper_id, "is_retracted": paper_id in retracted}
        for paper_id in ids
    }


def test_selection_is_pure_score_when_nothing_is_reserved() -> None:
    """Sources that reserve nothing keep the previous truncation exactly."""
    ranked = _ranked("A", "B", "C", "D")
    source_map = {"A": "pubmed", "B": "pubmed", "C": "corpus", "D": "corpus"}
    sources = [
        SearchSourceConfig(tool="corpus"),
        SearchSourceConfig(tool="pubmed"),
    ]
    assert select_within_budget(ranked, source_map, sources, 2) == ["A", "B"]


def test_reserved_slots_rescue_a_source_that_score_would_truncate() -> None:
    """The defect this fixes: a source ranked last never survived the cap.

    Corpus papers have no citation count and no publication year, so they
    sort below every indexed paper; with a budget of 2 they were always cut
    despite matching the question. Reserving keeps them without reordering
    the rest.
    """
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
    # Two corpus papers are guaranteed; the rest go to the best by score.
    assert selected == ["c1", "c2", "pm1", "pm2"]


def test_reserved_slots_are_not_padded_when_the_source_returns_fewer() -> None:
    """A reservation is a ceiling, not a quota to fill with nothing."""
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
    """The budget is the hard ceiling; reserving cannot enlarge the review."""
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
    """A reserved source whose top candidates are retracted is not seated.

    The defect this fixes: ``_fill_reserved_slots`` took a source's
    best-ranked N candidates with no retraction check, so a reserved source
    could seat a retracted paper solely because it out-ranked the source's
    own other candidates.
    """
    ranked = _ranked_retracted(("c1", "c2", "c3"), retracted={"c1", "c2"})
    source_map = {"c1": "corpus", "c2": "corpus", "c3": "corpus"}
    sources = [SearchSourceConfig(tool="corpus", reserved_slots=2)]

    selected = select_within_budget(ranked, source_map, sources, 3)

    assert "c1" not in selected
    assert "c2" not in selected
    assert selected == ["c3"]


def test_retracted_candidates_never_fill_an_underfilled_budget() -> None:
    """A budget the ranked pool can't fill still excludes retracted papers.

    The defect this fixes: ``_fill_remaining_by_score`` appended every
    remaining ranked id until the budget filled, and the retraction penalty
    only sorts a paper last -- it does not exclude it -- so an underfilled
    budget still admitted the retracted tail.
    """
    ranked = _ranked_retracted(("pm1", "pm2"), retracted={"pm2"})
    source_map = {"pm1": "pubmed", "pm2": "pubmed"}
    sources = [SearchSourceConfig(tool="pubmed")]

    selected = select_within_budget(ranked, source_map, sources, 5)

    assert selected == ["pm1"]


def test_a_reservation_short_on_non_retracted_papers_is_not_padded() -> None:
    """Excluding a source's retracted papers is not backfilled from elsewhere.

    ``reserved_slots`` is a ceiling on a source's own candidates, never a
    quota padded with another source's papers -- that property must hold
    for retracted exclusion exactly as it already holds for a source simply
    returning fewer papers than it reserved.
    """
    ranked = _ranked_retracted(("c1", "c2", "pm1"), retracted={"c2"})
    source_map = {"c1": "corpus", "c2": "corpus", "pm1": "pubmed"}
    sources = [
        SearchSourceConfig(tool="corpus", reserved_slots=2),
        SearchSourceConfig(tool="pubmed"),
    ]

    selected = select_within_budget(ranked, source_map, sources, 3)

    assert selected == ["c1", "pm1"]


def test_the_shipped_sources_reserve_no_slots() -> None:
    """The bundled literature-review sources all compete on score alone.

    The paper corpus was the only source that ever reserved slots (so its
    passages were not truncated away); now that the corpus reaches a run as an
    injected catalog rather than a search source, no bundled source reserves
    anything. `reserved_slots` remains a general capability of
    `SearchSourceConfig` (exercised by the tests above), just unused by the
    shipped config.
    """
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
    """A per-run disabled tool stops being searched.

    The app's connector toggles map to disable_tools; the registry
    reconciles source flags with tool flags at load time, and the search
    phase trusts ``get_enabled_search_sources()`` -- so the disabled
    source must already be gone here.
    """
    from co_scientist.config.registry import ToolRegistry

    registry = ToolRegistry(disabled_tools=["web_search"])
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None

    tools = [s.tool for s in workflow.get_enabled_search_sources()]
    assert "web_search" not in tools
    assert "pubmed_fulltext" in tools


def test_enabled_search_sources_keep_enabled_tools() -> None:
    """Nothing disabled means every configured source is searched."""
    from co_scientist.config.registry import ToolRegistry

    registry = ToolRegistry()
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None

    tools = [s.tool for s in workflow.get_enabled_search_sources()]
    assert "web_search" in tools


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
    """Cross-source parallelism survives the within-source change."""
    registry = make_tool_lookup_registry(
        {
            "src_a": make_tool_config(mcp_tool_name="search_a"),
            "src_b": make_tool_config(mcp_tool_name="search_b"),
        }
    )
    # Two sources x two queries must all be in flight together.
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
    tool_config = make_tool_config(mcp_tool_name="search_pubmed")
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
        make_search_run_ctx(client, errors),
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
    tool_config = make_tool_config(mcp_tool_name="search_pubmed")
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
        make_search_run_ctx(client, []),
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


@pytest.fixture
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


# =============================================================================
# _tag_source_name
# =============================================================================


# =============================================================================
# _search_source_for_query
# =============================================================================


# =============================================================================
# _search_single_source
# =============================================================================


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


@pytest.mark.usefixtures("_isolate_offline_router")
class TestLiteratureReviewSearchMultiSource:
    def test_build_query_tool_params_with_tool_config_maps_parameters(
        self,
    ) -> None:
        """A tool config maps canonical params and drops null-mapped entries."""
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
        """A transient non-JSON response is retried before losing the source."""

        async def no_delay(_: float) -> None:
            """Skip the production retry delay in this deterministic test."""

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
            """Skip the production backoff in this deterministic test."""

        # This test is about the outcome of exhausting the retry budget, not
        # about how long exhausting it takes.
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
        # Read from the constant: the retry budget is tuned against upstream
        # behavior, and a hardcoded copy here turns tuning it into a test break.
        assert len(client.calls) == search_query._SEARCH_ATTEMPTS

    async def test_search_single_source_missing_tool_config_returns_empty(
        self,
    ) -> None:
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

    async def test_search_single_source_collects_across_queries(self) -> None:
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

    async def test_phase2_collect_papers_multi_source_merges_and_dedupes(
        self,
    ) -> None:
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
                ["q1"],
                make_state(run_id="run-campaign"),
                config,
                client,
                errors,
            )

        assert [name for name, _ in client.calls] == ["search_pubmed"]
        assert set(metadata) == {"P1"}
        assert errors == []
