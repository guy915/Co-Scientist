"""Tests for ``literature_review_node`` orchestration.

The leaf helpers in ``literature_review.helpers`` are covered by
``test_literature_review_helpers_*`` and the in-file pure functions by
``test_literature_review_pure``; here we exercise the node's orchestration
along its fallback, happy, edge-case and research paths. The stubbed
seams live in ``tests/_literature_node.py``.

"""

from pathlib import Path
from typing import Any

import pytest

from co_scientist import cache_nodes
from co_scientist.agents.generation.literature_review import (
    literature_review_node,
)
from co_scientist.agents.generation.literature_review import node as lr
from co_scientist.agents.generation.literature_review import search as lr_search
from co_scientist.agents.generation.literature_review.research_phase import (
    ResearchOutcome,
)
from co_scientist.cache import NodeCache
from co_scientist.constants import LITERATURE_REVIEW_FAILED
from tests._literature_node import (
    _TWO_PAPERS,
    _make_event_recorder,
    _RaisingClient,
    _stub_node,
)
from tests._state import make_state

# =============================================================================
# No-MCP / server-unavailable fallback
# =============================================================================


async def test_server_unavailable_returns_failure_without_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the MCP server is unreachable the node fails fast.

    It returns the documented failure result (``articles_with_reasoning`` set to
    the failure sentinel, empty queries/articles) and never touches the MCP
    search client.
    """
    fake_client = _stub_node(monkeypatch, server_available=False)
    state = make_state(research_goal="cancer immunotherapy resistance")

    result = await literature_review_node(state)

    assert result["articles_with_reasoning"] == LITERATURE_REVIEW_FAILED
    assert result["literature_review_queries"] == []
    assert result["articles"] == []
    assert result["messages"][0]["metadata"]["error"] is True
    # The search seam was never reached.
    assert fake_client.calls == []


async def test_a_server_lost_mid_run_records_the_degradation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reaching this node at all means the server was up at setup.

    The graph routes around it when the run starts without one, so an
    outage found here is the same degradation arriving later -- and it
    has to reach the report the same way, or a run that lost its sources
    halfway through publishes as though it never needed them.
    """
    _stub_node(monkeypatch, server_available=False)
    state = make_state(research_goal="cancer immunotherapy resistance")
    state["context_enrichment_sources"] = [{"title": "an attachment"}]

    result = await literature_review_node(state)

    degradation = result["retrieval_degradation"]
    assert degradation["reason"] == "mcp_unreachable"
    # The run's own documents are unaffected by a server outage.
    assert degradation["floor"] == "run_attachments"


async def test_node_gate_is_server_reachability_not_source_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The node proceeds whenever the MCP server responds.

    Regression guard: the node once gated on a single source's availability
    (``check_pubmed``), so a PubMed outage aborted the whole node. The gate
    is now server reachability.
    This pins it: with the server reachable the node runs its search regardless
    of any one source's health, consulting ``check_mcp_available`` rather than a
    source-specific probe.
    """
    # The node must not reach for a source-specific availability probe; if it
    # imported one, this would catch a regression to the old coupling.
    assert not hasattr(lr, "check_literature_source_available")

    papers = {"PMID1": {"title": "A paper", "fulltext": "Body text."}}
    fake_client = _stub_node(
        monkeypatch,
        server_available=True,
        search_payload=papers,
        synthesis="REVIEW",
    )
    # Record that the gate consults server reachability, then let it pass.
    called: dict[str, bool] = {}

    async def fake_server_available(**_: Any) -> bool:
        called["check_mcp_available"] = True
        return True

    monkeypatch.setattr(lr, "check_mcp_available", fake_server_available)
    state = make_state(research_goal="cancer immunotherapy resistance")

    result = await literature_review_node(state)

    assert called.get("check_mcp_available") is True
    # The search seam WAS reached: the server being up is sufficient.
    assert fake_client.calls != []
    assert result["articles_with_reasoning"] == "REVIEW"


# =============================================================================
# Happy path
# =============================================================================


async def test_happy_path_populates_synthesis_and_articles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full single-source run yields synthesis, queries and Article objects.

    Two papers (both with ``fulltext``) are returned by the stubbed search, the
    query LLM yields two queries, the per-paper analysis LLM is stubbed, and the
    synthesis LLM returns canned text that lands in ``articles_with_reasoning``.
    """
    _stub_node(
        monkeypatch,
        server_available=True,
        search_payload=_TWO_PAPERS,
        queries=["query alpha", "query beta"],
        synthesis="SYNTHESIZED REVIEW",
    )
    state = make_state(research_goal="immune checkpoint resistance")

    result = await literature_review_node(state)

    assert result["articles_with_reasoning"] == "SYNTHESIZED REVIEW"
    # Queries are capped at 3; both stubbed queries survive.
    assert result["literature_review_queries"] == ["query alpha", "query beta"]
    # One Article per collected paper.
    articles = result["articles"]
    assert len(articles) == 2
    assert {a.source_id for a in articles} == {"PMID1", "PMID2"}
    assert {a.title for a in articles} == {
        "Tumor microenvironment review",
        "Immune checkpoint blockade",
    }
    # The success message records the counts.
    assert result["messages"][0]["metadata"]["phase"] == "literature_review"
    assert "error" not in result["messages"][0]["metadata"]


async def test_happy_path_falls_back_to_research_goal_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty query LLM response falls back to the research goal as a query.

    ``_phase1_generate_queries`` uses ``[research_goal]`` when neither the MCP
    nor the LLM path produces queries.
    """
    papers = {
        "PMID9": {
            "title": "Single paper",
            "fulltext": "Body text.",
        },
    }
    _stub_node(
        monkeypatch,
        server_available=True,
        search_payload=papers,
        queries=[],  # forces the research-goal fallback
        synthesis="REVIEW",
    )
    state = make_state(research_goal="rare query fallback goal")

    result = await literature_review_node(state)

    assert result["literature_review_queries"] == ["rare query fallback goal"]
    assert result["articles_with_reasoning"] == "REVIEW"
    assert len(result["articles"]) == 1


# =============================================================================
# Edge cases
# =============================================================================


async def test_no_papers_found_returns_failure_with_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty search result returns failure but still surfaces the queries.

    The node reaches the ``len(all_paper_metadata) == 0`` gate and returns the
    failure sentinel with the generated queries and no articles.
    """
    _stub_node(
        monkeypatch,
        server_available=True,
        search_payload={},  # no papers
        queries=["only query"],
    )
    state = make_state(research_goal="empty result goal")

    result = await literature_review_node(state)

    assert result["articles_with_reasoning"] == LITERATURE_REVIEW_FAILED
    assert result["literature_review_queries"] == ["only query"]
    assert result["articles"] == []
    assert result["messages"][0]["metadata"]["error"] is True


async def test_abstract_only_papers_are_analyzed_with_bounded_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit abstract supports analysis without claiming fulltext."""
    papers = {
        "PMID5": {
            "title": "Abstract-only paper",
            "abstract": "Just an abstract, no body.",
        },
    }
    _stub_node(
        monkeypatch,
        server_available=True,
        search_payload=papers,
        queries=["q"],
    )
    state = make_state(research_goal="abstract only goal")

    result = await literature_review_node(state)

    assert result["articles_with_reasoning"] == "SYNTHESIZED REVIEW"
    assert result["literature_review_queries"] == ["q"]
    assert len(result["articles"]) == 1
    assert result["articles"][0].source_id == "PMID5"
    assert result["articles"][0].content is None
    assert result["articles"][0].abstract == "Just an abstract, no body."
    assert result["articles"][0].used_in_analysis is True
    assert result["messages"][0]["metadata"]["articles_analyzed"] == 1


async def test_progress_callback_receives_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured progress callback receives start and completion events.

    Exercises the ``emit_progress`` seam along the happy path: the callback is
    invoked with at least the start and completion event names.
    """
    events: list[str] = []

    async def callback(event: str, _payload: dict[str, Any]) -> None:
        events.append(event)

    papers = {"PMID7": {"title": "P", "fulltext": "body"}}
    _stub_node(
        monkeypatch,
        server_available=True,
        search_payload=papers,
        queries=["q"],
        synthesis="REVIEW",
    )
    state = make_state(
        research_goal="callback goal", progress_callback=callback
    )

    await literature_review_node(state)

    assert "literature_review_start" in events
    assert "literature_review_complete" in events


async def test_no_papers_with_search_error_emits_error_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed search surfaces a distinct error event, not a silent empty run.

    When every search call raises, the node reports ``literature_review_error``
    with a non-zero ``search_errors_count`` and a sample of the causes, so a
    connection/transport failure is distinguishable from a search that
    legitimately found nothing.
    """
    events, callback = _make_event_recorder()

    # Reuse the standard stubs, then replace the client with one that raises on
    # every search call (query generation uses the stubbed LLM, not call_tool).
    _stub_node(
        monkeypatch, server_available=True, search_payload={}, queries=["q"]
    )

    async def fake_get_client(**_: Any) -> _RaisingClient:
        return _RaisingClient()

    monkeypatch.setattr(lr, "get_mcp_client", fake_get_client)

    state = make_state(
        research_goal="connection blip goal", progress_callback=callback
    )
    await literature_review_node(state)

    error_payloads = [p for e, p in events if e == "literature_review_error"]
    assert error_payloads, "expected a literature_review_error event"
    assert error_payloads[0]["search_errors_count"] >= 1
    assert any(
        "ConnectionError" in sample
        for sample in error_payloads[0]["search_error_sample"]
    )


async def test_no_papers_without_error_emits_empty_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A search that returns nothing without errors emits the empty event.

    Distinct from the error path: ``literature_review_empty`` with
    ``search_errors_count == 0``.
    """
    events, callback = _make_event_recorder()

    _stub_node(
        monkeypatch, server_available=True, search_payload={}, queries=["q"]
    )
    state = make_state(
        research_goal="genuinely empty goal", progress_callback=callback
    )
    await literature_review_node(state)

    empty_payloads = [p for e, p in events if e == "literature_review_empty"]
    assert empty_payloads, "expected a literature_review_empty event"
    assert empty_payloads[0]["search_errors_count"] == 0


# =============================================================================
# Phase 6: what research adds to the node's result
# =============================================================================


def _stub_research(
    monkeypatch: pytest.MonkeyPatch, section: str = "\n\n## Research\nfound"
) -> None:
    """Make phase 6 return one finding, one paper and a ledger."""

    async def fake_phase(*_: Any, **__: Any) -> ResearchOutcome:
        return ResearchOutcome(
            ledger={"threads": [], "calls": [], "findings": []},
            records={
                "PMID7": {
                    "title": "Researched paper",
                    "abstract": "Abstract seven.",
                    "retrieval_call_id": "call-7",
                    "_source_name": "alpha",
                }
            },
            section=section,
        )

    monkeypatch.setattr(lr, "run_research_phase", fake_phase)


async def test_research_reaches_the_result_the_run_persists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ledger is the run's record of what was searched and why.

    Without it on the result, the phase's provenance never leaves the
    node and no evidence row can name the search that found it.
    """
    _stub_node(
        monkeypatch,
        server_available=True,
        search_payload=_TWO_PAPERS,
        queries=["query alpha"],
        synthesis="SYNTHESIZED REVIEW",
    )
    _stub_research(monkeypatch)

    result = await literature_review_node(make_state(research_goal="goal"))

    assert result["research_ledgers"] == [
        {"threads": [], "calls": [], "findings": []}
    ]
    assert "## Research" in result["articles_with_reasoning"]
    researched = [a for a in result["articles"] if a.source_id == "PMID7"]
    assert len(researched) == 1
    assert researched[0].retrieval_call_id == "call-7"


async def test_cached_research_keeps_ledger_and_article_call_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A node cache hit keeps the deep-research provenance as one record.

    The first pass writes the article and its ledger; the second pass must
    return both from cache without repeating the Phase 2 search.
    """
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
    """A cached article call id without its ledger cannot be replayed."""
    from co_scientist.models import Article

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
    config = lr._get_search_config(state)
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
    from co_scientist.models import Article

    cache = NodeCache(str(tmp_path), enabled=cache_enabled, ttl_seconds=None)
    monkeypatch.setattr(cache_nodes, "campaign_free_mode", lambda: False)
    monkeypatch.setattr(cache_nodes, "current_api_key", lambda: None)
    client = _stub_node(monkeypatch, server_available=False)
    monkeypatch.setattr(lr, "get_node_cache", lambda: cache)
    state = make_state(
        research_goal="ordinary goal",
        dev_test_lit_tools_isolation=force_cache,
    )
    config = lr._get_search_config(state)
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


async def test_a_failed_review_stays_failed_however_much_research_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Downstream generation compares this value to the sentinel exactly.

    Appending a research section to it would make a review that produced
    no analyses read as one that succeeded.
    """
    _stub_node(
        monkeypatch,
        server_available=True,
        search_payload=_TWO_PAPERS,
        queries=["query alpha"],
        synthesis=LITERATURE_REVIEW_FAILED,
    )
    _stub_research(monkeypatch)

    result = await literature_review_node(make_state(research_goal="goal"))

    assert result["articles_with_reasoning"] == LITERATURE_REVIEW_FAILED
    # The papers and the ledger still survive; only the text is held back.
    assert result["research_ledgers"]
    assert any(a.source_id == "PMID7" for a in result["articles"])


async def test_tool_error_envelope_reaches_source_failure_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, callback = _make_event_recorder()
    _stub_node(monkeypatch, server_available=True, queries=["q"])

    class Client:
        async def call_tool(self, _name: str, **_params: Any) -> str:
            return (
                "Error calling tool 'search_europepmc': "
                "Europe PMC unavailable: HTTP 429; Retry-After=60"
            )

    async def get_client(**_: Any) -> Client:
        return Client()

    monkeypatch.setattr(lr, "get_mcp_client", get_client)
    await literature_review_node(
        make_state(research_goal="public evidence", progress_callback=callback)
    )
    errors = [p for e, p in events if e == "literature_review_error"]
    assert errors and errors[0]["search_errors_count"] > 0
    assert any(
        "Europe PMC" in s and "Retry-After=60" in s
        for s in errors[0]["search_error_sample"]
    )
    assert not any(e == "literature_review_empty" for e, _ in events)
