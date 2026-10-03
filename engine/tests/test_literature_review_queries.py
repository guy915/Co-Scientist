"""Offline contracts for literature review queries."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

import co_scientist.cache as cache_nodes
from co_scientist.agents.generation.literature_review import (
    literature_review_node,
    queries,
    synthesis,
)
from co_scientist.agents.generation.literature_review import node as lr
from co_scientist.agents.generation.literature_review import (
    orchestration as lr_orchestration,
)
from co_scientist.cache import NodeCache
from co_scientist.config import ToolConfig, WorkflowConfig
from co_scientist.constants import (
    LITERATURE_REVIEW_FAILED,
    LITERATURE_SYNTHESIS_FALLBACK_MAX_CHARS,
)
from co_scientist.evidence import search
from co_scientist.evidence import search as lr_search
from co_scientist.evidence.search_query import broadened_queries
from co_scientist.evidence.search_support import SearchConfig
from co_scientist.mcp_client import MCPToolClient
from co_scientist.models import Article
from tests._mcp import (
    FakeCallToolClient,
    make_tool_lookup_registry,
    make_tool_results_client,
)
from tests._research_fakes import (
    _TWO_PAPERS,
    _stub_node,
    _stub_research,
    make_search_config,
    make_tool_config,
)
from tests._state import make_state


def _search_config(**overrides: Any) -> SearchConfig:
    """Build a SearchConfig over the pubmed source, overriding given fields.

    The pubmed tool and source names are this module's own -- query
    generation reads them into the prompt -- so they stay explicit here
    rather than inheriting the shared builder's placeholders.

    Args:
        **overrides: Any SearchConfig fields to set (e.g. ``workflow``,
            ``tool_registry``).

    Returns:
        A SearchConfig naming pubmed as the search source.
    """
    return make_search_config(
        search_tool_name="pubmed_search_with_fulltext",
        source_name="pubmed",
        **overrides,
    )


# =============================================================================
# _generate_queries_via_mcp
# =============================================================================


async def test_generate_queries_via_mcp_success_returns_parsed_queries() -> (
    None
):
    """A successful MCP call returns the parsed query list."""
    client = FakeCallToolClient(response=["query one", "query two"])

    result = await queries._generate_queries_via_mcp(
        cast(MCPToolClient, client), "goal", "qgen_tool", "boolean"
    )

    assert result == ["query one", "query two"]
    assert client.calls == [
        ("qgen_tool", {"research_goal": "goal", "query_format": "boolean"})
    ]


async def test_generate_queries_via_mcp_error_returns_empty_list() -> None:
    """A raised exception falls back to an empty list, not a raise.

    An empty list here is the signal that lets ``_phase1_generate_queries``
    fall through to LLM-based generation.
    """
    client = FakeCallToolClient(error=RuntimeError("mcp down"))

    result = await queries._generate_queries_via_mcp(
        cast(MCPToolClient, client), "goal", "qgen_tool", "boolean"
    )

    assert result == []


# =============================================================================
# _generate_queries_via_llm
# =============================================================================


async def test_generate_queries_via_llm_error_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raised exception from the LLM call falls back to an empty list."""

    async def _raise(**_: Any) -> dict[str, Any]:
        raise RuntimeError("llm down")

    monkeypatch.setattr(queries, "call_llm_json", _raise)
    state = make_state(research_goal="goal x")

    result = await queries._generate_queries_via_llm(state, _search_config())

    assert result == []


# =============================================================================
# _resolve_query_format
# =============================================================================


def test_resolve_query_format_defaults_to_boolean_when_unset() -> None:
    """An empty ``query_format`` on the workflow falls back to ``boolean``."""
    workflow = WorkflowConfig(query_format="")
    assert queries._resolve_query_format(workflow) == "boolean"


def test_resolve_query_format_honors_configured_value() -> None:
    """A configured ``query_format`` is returned unchanged."""
    workflow = WorkflowConfig(query_format="natural_language")
    assert queries._resolve_query_format(workflow) == "natural_language"


# =============================================================================
# _resolve_query_generation_tool
# =============================================================================


def test_resolve_query_generation_tool_missing_tool_config_returns_none() -> (
    None
):
    """A configured tool id the registry can't resolve returns None."""
    workflow = WorkflowConfig(query_generation_tool="qgen_missing")
    config = _search_config(
        tool_registry=make_tool_lookup_registry({}),
        workflow=workflow,
    )

    assert queries._resolve_query_generation_tool(config) is None


def test_resolve_query_generation_tool_returns_name_and_format() -> None:
    """A resolvable tool id returns its MCP name and configured format."""
    tool_config = make_tool_config(mcp_tool_name="qgen_mcp")
    workflow = WorkflowConfig(
        query_generation_tool="qgen_tool", query_format="natural_language"
    )
    config = _search_config(
        tool_registry=make_tool_lookup_registry({"qgen_tool": tool_config}),
        workflow=workflow,
    )

    assert queries._resolve_query_generation_tool(config) == (
        "qgen_mcp",
        "natural_language",
    )


# =============================================================================
# _try_mcp_query_generation
# =============================================================================


async def test_try_mcp_query_generation_calls_the_resolved_tool() -> None:
    """A resolved query-generation tool is invoked via the MCP client."""
    tool_config = make_tool_config(mcp_tool_name="qgen_mcp")
    workflow = WorkflowConfig(
        query_generation_tool="qgen_tool", query_format="boolean"
    )
    config = _search_config(
        tool_registry=make_tool_lookup_registry({"qgen_tool": tool_config}),
        workflow=workflow,
    )
    client = FakeCallToolClient(response=["alpha", "beta"])
    state = make_state(research_goal="goal x")

    result = await queries._try_mcp_query_generation(
        state, config, cast(MCPToolClient, client)
    )

    assert result == ["alpha", "beta"]
    assert client.calls[0][0] == "qgen_mcp"


# =============================================================================
# _phase1_generate_queries -- final fallback to the research goal
# =============================================================================


async def test_final_fallback_distills_the_goal_instead_of_sending_it_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both generators fail, the fallback query is keyword-shaped.

    Sending the prose goal verbatim -- articles, punctuation, question
    words and all -- hands Entrez a query that collapses under its own
    AND-every-term semantics before the broadening ladder even runs. The
    fallback must strip that down to the same keyword shape the query-
    generation prompt itself asks the model for.
    """

    async def _raise(**_: Any) -> dict[str, Any]:
        raise RuntimeError("llm down")

    monkeypatch.setattr(queries, "call_llm_json", _raise)
    state = make_state(
        research_goal=(
            "How does mifepristone affect the glucocorticoid receptor"
            " in glioblastoma?"
        )
    )
    client = FakeCallToolClient(response=[])

    phase_result = await queries._phase1_generate_queries(
        state, _search_config(), cast(MCPToolClient, client)
    )
    result = phase_result.queries

    assert result != [state["research_goal"]]
    assert len(result) == 1
    # Both generators were exhausted before the keyword fallback, so the
    # LLM-fallback path did run (and failed) -- it still spent one call.
    assert phase_result.llm_calls == 1
    fallback = result[0]
    assert "?" not in fallback
    for stopword in ("how", "does", "the", "in"):
        assert stopword not in fallback.lower().split()
    for keyword in (
        "mifepristone",
        "glucocorticoid",
        "receptor",
        "glioblastoma",
    ):
        assert keyword in fallback.lower()


_NINE_TERMS = (
    "mifepristone glucocorticoid receptor antagonist glioblastoma "
    "blood brain barrier PD-L1"
)


def test_ladder_narrows_to_the_range_that_actually_returns_records() -> None:
    """The rungs are the measured recovery points, not arbitrary lengths."""
    assert broadened_queries(_NINE_TERMS) == [
        _NINE_TERMS,
        # 1 record on PubMed, where the nine-term form returns none.
        "mifepristone glucocorticoid receptor antagonist glioblastoma",
        # 2811 records; the floor still names a topic.
        "mifepristone glucocorticoid",
    ]


def test_a_query_already_short_enough_is_left_alone() -> None:
    """Two terms name a topic; one is a subject heading. Neither broadens."""
    assert broadened_queries("mifepristone glioblastoma") == [
        "mifepristone glioblastoma"
    ]
    assert broadened_queries("copper") == ["copper"]


class _QueryScriptedClient:
    """Fake MCP client returning a scripted response per exact query."""

    def __init__(self, responses: dict[str, Any]) -> None:
        """Map each exact query string to its response or exception."""
        self._responses = responses
        self.queries: list[str] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Record the query and return (or raise) its scripted outcome."""
        query = str(kwargs["query"])
        self.queries.append(query)
        outcome = self._responses[query]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _papers(*ids: str) -> dict[str, Any]:
    """A search response carrying the given paper ids."""
    return {i: {"title": i} for i in ids}


def _ctx(client: Any, errors: list[str]) -> search._SearchRunContext:
    """A run context over the shared slug for search calls."""
    return search._SearchRunContext(
        slug="slug",
        run_id="run1",
        mcp_client=cast(MCPToolClient, client),
        errors=errors,
    )


async def _search(client: Any, query: str, errors: list[str]) -> Any:
    """Run one source query through the function under test."""
    return await search._search_source_for_query(
        query,
        _ctx(client, errors),
        ToolConfig(server="s", mcp_tool_name="search_pubmed"),
        "pubmed",
        papers_per_query=4,
    )


async def test_an_empty_query_is_retried_in_broader_form() -> None:
    """The over-constrained query returns nothing; the broader one lands."""
    ladder = broadened_queries(_NINE_TERMS)
    client = _QueryScriptedClient(
        {
            ladder[0]: _papers(),
            ladder[1]: _papers("p1", "p2"),
        }
    )
    errors: list[str] = []

    result = await _search(client, _NINE_TERMS, errors)

    assert sorted(result) == ["p1", "p2"]
    assert client.queries == [ladder[0], ladder[1]]
    # Zero results is not an error: nothing broke, the query was too narrow.
    assert errors == []


async def test_broadening_walks_to_the_floor_when_it_has_to() -> None:
    """Some queries only return records at the shortest form."""
    ladder = broadened_queries(_NINE_TERMS)
    client = _QueryScriptedClient(
        {
            ladder[0]: _papers(),
            ladder[1]: _papers(),
            ladder[2]: _papers("p9"),
        }
    )

    result = await _search(client, _NINE_TERMS, [])

    assert list(result) == ["p9"]
    assert client.queries == ladder


async def test_a_query_that_returns_records_is_never_broadened() -> None:
    """Broadening is a recovery path, not a second search on every query."""
    client = _QueryScriptedClient({_NINE_TERMS: _papers("p1")})

    result = await _search(client, _NINE_TERMS, [])

    assert list(result) == ["p1"]
    assert client.queries == [_NINE_TERMS]


async def test_a_failed_search_is_not_retried_broader() -> None:
    """The query was not what failed, so a shorter one fails the same way.

    Retrying would multiply an outage across every query in the run rather
    than recovering anything.
    """
    client = _QueryScriptedClient({_NINE_TERMS: RuntimeError("backend down")})
    errors: list[str] = []

    result = await _search(client, _NINE_TERMS, errors)

    assert result == {}
    # _call_search_tool retries a transient failure itself, but every attempt
    # is the same query: the failure never advances the ladder.
    assert set(client.queries) == {_NINE_TERMS}
    assert errors and "backend down" in errors[0]


# =============================================================================
# The single-source path broadens on the same terms
# =============================================================================


def _single_source_config() -> SearchConfig:
    """The config shape a ``primary_search``-only deployment resolves to.

    ``examples/arxiv_only.yaml`` and ``examples/google_scholar.yaml`` both
    declare a ``primary_search`` with no ``search_sources``, which is exactly
    what ``WorkflowConfig.is_multi_source()`` reads, so Phase 2 dispatches
    every one of their queries to the single-source path.
    """
    return SearchConfig(
        tool_registry=None,
        workflow=None,
        is_multi_source=False,
        search_tool_name="search_pubmed",
        search_tool_config=None,
        source_name="pubmed",
        papers_to_read_count=4,
        is_dev_mode=False,
    )


async def _search_single(client: Any, query: str, errors: list[str]) -> Any:
    """Run one query through the single-source path."""
    return await search._search_single_query(
        query, 1, 4, _ctx(client, errors), _single_source_config()
    )


async def test_the_single_source_path_broadens_too() -> None:
    """One configured source is the case that can least afford the miss.

    Nothing about an AND-ed keyword query is multi-source-specific -- it is
    how the back ends read the query -- and a lone source has no sibling to
    make up for what it returns nothing for. Left unbroadened, a
    single-source deployment silently gets the pre-broadening behavior.
    """
    ladder = broadened_queries(_NINE_TERMS)
    client = _QueryScriptedClient(
        {ladder[0]: _papers(), ladder[1]: _papers("p1", "p2")}
    )
    errors: list[str] = []

    result = await _search_single(client, _NINE_TERMS, errors)

    assert sorted(result) == ["p1", "p2"]
    assert client.queries == [ladder[0], ladder[1]]
    # Zero results is not an error here either: the query was too narrow.
    assert errors == []


async def test_a_failed_single_source_search_still_names_its_query() -> None:
    """Sharing the search body must not relabel single-source diagnostics.

    The single-source path has no source name to report -- one tool serves
    every query -- so the query index is what makes an aggregated error
    traceable back to a query.
    """
    client = _QueryScriptedClient({_NINE_TERMS: RuntimeError("backend down")})
    errors: list[str] = []

    result = await _search_single(client, _NINE_TERMS, errors)

    assert result == {}
    assert set(client.queries) == {_NINE_TERMS}
    assert errors == ["query 1: RuntimeError: backend down"]


async def test_phase4_synthesize_no_analyses_returns_failure_sentinel() -> None:
    """An empty analyses list returns the sentinel without calling the LLM."""
    state = make_state(research_goal="goal")

    result = await synthesis._phase4_synthesize([], state)

    assert result == LITERATURE_REVIEW_FAILED


async def test_phase4_synthesize_llm_failure_with_analyses_degrades_to_rollup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A synthesis LLM failure must not discard successfully-retrieved papers.

    Losing the synthesis *prose* should not delete the *retrieval* -- the
    per-paper analyses cost real LLM calls to produce, so a failed synthesis
    call degrades to a deterministic roll-up of them rather than the
    failure sentinel.
    """

    async def _raise(**_: Any) -> str:
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(synthesis, "call_llm", _raise)
    state = make_state(research_goal="goal")
    paper_analyses = [
        {
            "paper_id": "P1",
            "metadata": {"title": "A paper about X"},
            "analysis": {
                "key_findings": "X causes Y under condition Z.",
                "gaps_identified": "Mechanism of Y is unclear.",
                "unexplored_areas": "Nobody has tried blocking pathway W.",
            },
        }
    ]

    result = await synthesis._phase4_synthesize(paper_analyses, state)

    assert result != LITERATURE_REVIEW_FAILED
    # Honest about what it is: a mechanical roll-up, not a synthesis.
    assert "not an LLM synthesis" in result
    # The retrieved content actually survives into the fallback text --
    # gaps_identified and unexplored_areas are both hypothesis-generative
    # (what's missing, what nobody has tried), so both must survive.
    assert "A paper about X" in result
    assert "X causes Y under condition Z." in result
    assert "Mechanism of Y is unclear." in result
    assert "Nobody has tried blocking pathway W." in result


async def test_phase4_synthesize_fallback_rollup_is_length_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A huge pool of analyses must not blow a downstream prompt's budget.

    Also the crowded case for the per-paper allowance: with 50 papers each
    carrying long text in all three signal fields, the cap is spent
    thinly across papers instead of the first few consuming it all --
    so a paper well past where an unbounded roll-up would have run out
    (5-6 papers' worth of untruncated text exhausts 8000 chars) still
    gets a representation, with all three of its signals present.
    """

    async def _raise(**_: Any) -> str:
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(synthesis, "call_llm", _raise)
    state = make_state(research_goal="goal")
    paper_analyses = [
        {
            "paper_id": f"P{i}",
            "metadata": {"title": f"Paper number {i}"},
            "analysis": {
                "key_findings": "Finding text. " * 50,
                "gaps_identified": "Gap text. " * 50,
                "unexplored_areas": "Unexplored text. " * 50,
            },
        }
        for i in range(50)
    ]

    result = await synthesis._phase4_synthesize(paper_analyses, state)

    # truncate() may append a short "..." suffix past the raw cap; the
    # bound that matters is "close to the cap", not "byte-exact".
    assert len(result) <= LITERATURE_SYNTHESIS_FALLBACK_MAX_CHARS + 10
    # A paper far past what an unbounded roll-up could ever have reached
    # still made it in, with all three of its signals represented.
    assert "Paper number 20" in result
    assert "Finding text." in result
    assert "Gap text." in result
    assert "Unexplored text." in result


async def test_phase4_synthesize_no_analyses_never_reaches_the_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The empty-analyses branch never reaches the LLM call at all."""

    async def _raise(**_: Any) -> str:
        raise AssertionError("must not be called with no analyses")

    monkeypatch.setattr(synthesis, "call_llm", _raise)
    state = make_state(research_goal="goal")

    result = await synthesis._phase4_synthesize([], state)

    assert result == LITERATURE_REVIEW_FAILED


async def test_cached_research_keeps_ledger_and_article_call_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A hit reuses both the search result and its research ledger."""
    cache = NodeCache(str(tmp_path), enabled=True, ttl_seconds=None)
    monkeypatch.setattr(cache_nodes, "campaign_free_mode", lambda: False)
    monkeypatch.setattr(cache_nodes, "current_api_key", lambda: None)
    client = _stub_node(
        monkeypatch,
        server_available=True,
        search_payload=_TWO_PAPERS,
        queries=["query alpha"],
        synthesis="SYNTHESIZED REVIEW",
    )

    async def keep_lexical_order(
        ranked: dict[str, dict[str, Any]], _config: Any
    ) -> dict[str, dict[str, Any]]:
        return ranked

    monkeypatch.setattr(
        lr_search, "_apply_semantic_relevance_if_enabled", keep_lexical_order
    )
    monkeypatch.setattr(lr, "get_node_cache", lambda: cache)
    _stub_research(monkeypatch)
    state = make_state(research_goal="goal", research_tier="extended")

    first = await literature_review_node(state)
    first_search_count = len(client.calls)
    cached = await literature_review_node(state)

    assert first["research_ledgers"] == cached["research_ledgers"]
    researched = [a for a in cached["articles"] if a.source_id == "PMID7"]
    assert len(researched) == 1
    assert researched[0].retrieval_call_id == "call-7"
    assert len(client.calls) == first_search_count


async def test_legacy_research_cache_entry_is_refreshed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An article call ID without its ledger makes the cache entry stale."""
    cache = NodeCache(str(tmp_path), enabled=True, ttl_seconds=None)
    monkeypatch.setattr(cache_nodes, "campaign_free_mode", lambda: False)
    monkeypatch.setattr(cache_nodes, "current_api_key", lambda: None)
    client = _stub_node(
        monkeypatch,
        server_available=True,
        search_payload=_TWO_PAPERS,
        queries=["query alpha"],
        synthesis="REFRESHED REVIEW",
    )

    async def keep_lexical_order(
        ranked: dict[str, dict[str, Any]], _config: Any
    ) -> dict[str, dict[str, Any]]:
        return ranked

    monkeypatch.setattr(
        lr_search, "_apply_semantic_relevance_if_enabled", keep_lexical_order
    )
    monkeypatch.setattr(lr, "get_node_cache", lambda: cache)
    _stub_research(monkeypatch)
    state = make_state(research_goal="goal", research_tier="extended")
    config = lr.search_config_for(state)
    cache.set(
        "literature_review",
        {
            "articles": [
                Article(
                    title="Legacy researched paper",
                    retrieval_call_id="call-legacy",
                )
            ],
            "articles_with_reasoning": "LEGACY CACHE",
        },
        **lr._literature_cache_params(state, config),
    )

    result = await literature_review_node(state)

    assert (
        result["articles_with_reasoning"]
        == "REFRESHED REVIEW\n\n## Research\nfound"
    )
    assert result["research_ledgers"]
    assert client.calls


@pytest.mark.parametrize(
    ("cache_enabled", "force_cache"), [(True, False), (False, True)]
)
async def test_ordinary_cache_hit_without_research_provenance_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cache_enabled: bool,
    force_cache: bool,
) -> None:
    """Ordinary Phase 2 articles have no ledger and remain cacheable."""
    cache = NodeCache(str(tmp_path), enabled=cache_enabled, ttl_seconds=None)
    monkeypatch.setattr(cache_nodes, "campaign_free_mode", lambda: False)
    monkeypatch.setattr(cache_nodes, "current_api_key", lambda: None)
    client = _stub_node(monkeypatch, server_available=False)
    monkeypatch.setattr(lr, "get_node_cache", lambda: cache)
    state = make_state(
        research_goal="ordinary goal",
        dev_test_lit_tools_isolation=force_cache,
    )
    config = lr.search_config_for(state)
    cache.set(
        "literature_review",
        {
            "articles": [Article(title="Ordinary Phase 2 paper")],
            "articles_with_reasoning": "ORDINARY CACHED REVIEW",
        },
        force=force_cache,
        **lr._literature_cache_params(state, config),
    )

    result = await literature_review_node(state)

    assert result["articles_with_reasoning"] == "ORDINARY CACHED REVIEW"
    assert client.calls == []


async def _boom(*_: Any, **__: Any) -> Any:
    """Stand in for a phase whose external dependency went down."""
    raise RuntimeError("external dependency refused the call")


async def _enrichment_ok(*_: Any, **__: Any) -> tuple[str, list[Any]]:
    """Stand in for a context-enrichment phase that succeeded."""
    return "KRAS activates MAPK", [{"id": "kg:1"}]


async def _fetch_content_and_enrichment() -> tuple[str, list[Any]]:
    """Drive the phase pair with the module's own fixtures."""
    return await lr_orchestration._fetch_content_and_enrichment(
        {},
        {},
        make_search_config(),
        make_tool_results_client(),
        make_state(research_goal="Study of KRAS in cancer"),
    )


async def test_failed_retrieval_keeps_the_enrichment_it_ran_beside(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retrieval fault does not discard the enrichment branch's result."""
    monkeypatch.setattr(lr_orchestration, "_discover_then_fetch_content", _boom)
    monkeypatch.setattr(
        lr_orchestration, "_phase2_6_fetch_context_enrichment", _enrichment_ok
    )

    context, sources = await _fetch_content_and_enrichment()

    assert context == "KRAS activates MAPK"
    assert sources == [{"id": "kg:1"}]


async def test_failed_enrichment_degrades_to_empty_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An enrichment fault leaves the node with the empty context it handles."""
    retrieved: list[str] = []

    async def _retrieval_ok(*_: Any, **__: Any) -> None:
        retrieved.append("papers")

    monkeypatch.setattr(
        lr_orchestration, "_discover_then_fetch_content", _retrieval_ok
    )
    monkeypatch.setattr(
        lr_orchestration, "_phase2_6_fetch_context_enrichment", _boom
    )

    context, sources = await _fetch_content_and_enrichment()

    assert retrieved == ["papers"]
    assert (context, sources) == ("", [])
