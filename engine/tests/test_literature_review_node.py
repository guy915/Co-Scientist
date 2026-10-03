"""Offline contracts for literature review node."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest

from co_scientist.agents.generation.literature_review import (
    literature_review_node,
)
from co_scientist.agents.generation.literature_review import node as lr
from co_scientist.agents.generation.literature_review import (
    orchestration as lr_content,
)
from co_scientist.config import (
    SearchSourceConfig,
    ToolConfig,
    ToolRegistry,
    WorkflowConfig,
)
from co_scientist.constants import LITERATURE_REVIEW_FAILED
from co_scientist.evidence import run_config
from co_scientist.evidence.retrieval_support import ContentToolConfig
from co_scientist.mcp_client import MCPToolClient
from tests._mcp import FakeToolResultsClient, make_tool_results_client
from tests._mcp import make_tool_lookup_registry as _registry
from tests._research_fakes import (
    _TWO_PAPERS,
    _make_event_recorder,
    _RaisingClient,
    _stub_node,
    _stub_research,
    make_search_config,
)
from tests._state import make_state

# =============================================================================
# _discover_pdf_link
# =============================================================================


async def test_discover_pdf_link_no_landing_url_skips_call() -> None:
    """A paper with no value under url_field is skipped without a tool call."""
    client = FakeToolResultsClient()
    result = await lr_content._discover_pdf_link(
        "p1", {}, "discover_tool", "url", cast(MCPToolClient, client)
    )
    assert result == ("p1", None)
    assert client.calls == []


async def test_discover_pdf_link_success_returns_parsed_url() -> None:
    """A successful discovery call yields the parsed PDF URL."""
    payload = json.dumps(["http://example.test/paper.pdf"])
    client = FakeToolResultsClient(results={"discover_tool": payload})

    result = await lr_content._discover_pdf_link(
        "p1",
        {"url": "http://example.test/landing"},
        "discover_tool",
        "url",
        cast(MCPToolClient, client),
    )

    assert result == ("p1", "http://example.test/paper.pdf")
    assert client.calls == [
        ("discover_tool", {"url": "http://example.test/landing"})
    ]


async def test_discover_pdf_link_no_pdf_found_returns_none() -> None:
    """A discovery call that yields no PDF URL still returns cleanly."""
    client = FakeToolResultsClient(results={"discover_tool": json.dumps([])})

    result = await lr_content._discover_pdf_link(
        "p1",
        {"url": "http://example.test/landing"},
        "discover_tool",
        "url",
        cast(MCPToolClient, client),
    )

    assert result == ("p1", None)


async def test_discover_pdf_link_tool_error_returns_none() -> None:
    """A raising discovery tool leaves the paper without a pdf_url."""
    client = FakeToolResultsClient(error_tools={"discover_tool"})

    result = await lr_content._discover_pdf_link(
        "p1",
        {"url": "http://example.test/landing"},
        "discover_tool",
        "url",
        cast(MCPToolClient, client),
    )

    assert result == ("p1", None)


# =============================================================================
# _apply_metadata_field (pdf_url)
# =============================================================================


def test_apply_metadata_field_pdf_url_updates_matching_papers() -> None:
    """Discovered URLs are written back only for papers present with a hit."""
    metadata = {"p1": {"title": "A"}, "p2": {"title": "B"}}
    results = [
        ("p1", "http://x/a.pdf"),
        ("p2", None),  # no discovery: left untouched
        ("missing", "http://x/c.pdf"),  # not in metadata: ignored
    ]

    count = lr_content._apply_metadata_field(metadata, results, "pdf_url")

    assert count == 1
    assert metadata["p1"]["pdf_url"] == "http://x/a.pdf"
    assert "pdf_url" not in metadata["p2"]


def test_apply_metadata_field_empty_list() -> None:
    """An empty results list updates nothing and counts zero."""
    metadata: dict[str, dict[str, Any]] = {"p1": {"title": "A"}}
    assert lr_content._apply_metadata_field(metadata, [], "pdf_url") == 0


# =============================================================================
# _run_pdf_discovery
# =============================================================================


async def test_run_pdf_discovery_mixed_success_and_failure() -> None:
    """Parallel discovery applies successful hits and skips failed lookups."""
    metadata = {
        "p1": {"url": "http://landing1"},
        "p2": {"url": "http://landing2"},
    }
    client = FakeToolResultsClient(
        results={"good_tool": json.dumps(["http://x/p1.pdf"])},
        error_tools={"bad_tool"},
    )
    papers_needing_discovery = [
        ("p1", metadata["p1"], "good_tool", "url"),
        ("p2", metadata["p2"], "bad_tool", "url"),
    ]

    count = await lr_content._run_pdf_discovery(
        papers_needing_discovery, cast(MCPToolClient, client), metadata
    )

    assert count == 1
    assert metadata["p1"]["pdf_url"] == "http://x/p1.pdf"
    assert "pdf_url" not in metadata["p2"]


# =============================================================================
# _phase2_4_discover_pdf_links
# =============================================================================


async def test_phase2_4_no_workflow_is_noop() -> None:
    """With no workflow configured, discovery config is empty and no-op."""
    metadata = {"p1": {"url": "http://landing"}}
    client = make_tool_results_client()

    await lr_content._phase2_4_discover_pdf_links(
        metadata, {}, make_search_config(), client
    )

    assert "pdf_url" not in metadata["p1"]
    assert cast(FakeToolResultsClient, client).calls == []


async def test_phase2_4_no_eligible_papers_is_noop() -> None:
    """A configured discovery tool with nothing eligible makes no calls."""
    workflow = WorkflowConfig(
        pdf_discovery_tool="discover", pdf_discovery_url_field="url"
    )
    registry = _registry(
        {"discover": ToolConfig(server="s", mcp_tool_name="mcp_discover")}
    )
    metadata = {"p1": {"pdf_url": "http://already.pdf"}}
    client = make_tool_results_client()

    await lr_content._phase2_4_discover_pdf_links(
        metadata,
        {},
        make_search_config(workflow=workflow, tool_registry=registry),
        client,
    )

    assert cast(FakeToolResultsClient, client).calls == []


async def test_phase2_4_success_populates_pdf_url() -> None:
    """An eligible paper gets its pdf_url discovered and written back."""
    workflow = WorkflowConfig(
        pdf_discovery_tool="discover", pdf_discovery_url_field="url"
    )
    registry = _registry(
        {"discover": ToolConfig(server="s", mcp_tool_name="mcp_discover")}
    )
    metadata = {"p1": {"url": "http://landing"}}
    client = make_tool_results_client(
        results={"mcp_discover": json.dumps(["http://x/found.pdf"])}
    )

    await lr_content._phase2_4_discover_pdf_links(
        metadata,
        {},
        make_search_config(workflow=workflow, tool_registry=registry),
        client,
    )

    assert metadata["p1"]["pdf_url"] == "http://x/found.pdf"


# =============================================================================
# _fetch_paper_content
# =============================================================================


async def test_fetch_paper_content_no_url_skips_call() -> None:
    """A paper with no value under url_field is skipped without a tool call."""
    client = FakeToolResultsClient()
    cfg = ContentToolConfig(
        mcp_tool_name="content_tool", url_field="pdf_url", content_params={}
    )

    result = await lr_content._fetch_paper_content(
        "p1", {}, cfg, cast(MCPToolClient, client), {}
    )

    assert result == ("p1", None)
    assert client.calls == []


async def test_fetch_paper_content_success_resolves_params() -> None:
    """A successful fetch resolves placeholders and returns the content."""
    client = FakeToolResultsClient(
        results={"content_tool": {"content": "the fetched body"}}
    )
    cfg = ContentToolConfig(
        mcp_tool_name="content_tool",
        url_field="pdf_url",
        content_params={"goal": "{research_goal}"},
    )
    runtime_context = {"research_goal": "understand KRAS signaling"}

    result = await lr_content._fetch_paper_content(
        "p1",
        {"pdf_url": "http://x/p1.pdf"},
        cfg,
        cast(MCPToolClient, client),
        runtime_context,
    )

    assert result == ("p1", "the fetched body")
    assert client.calls == [
        (
            "content_tool",
            {
                "url": "http://x/p1.pdf",
                "goal": "understand KRAS signaling",
            },
        )
    ]


async def test_fetch_paper_content_tool_error_returns_none() -> None:
    """A raising content tool leaves the paper without fulltext."""
    client = FakeToolResultsClient(error_tools={"content_tool"})
    cfg = ContentToolConfig(
        mcp_tool_name="content_tool", url_field="pdf_url", content_params={}
    )

    result = await lr_content._fetch_paper_content(
        "p1",
        {"pdf_url": "http://x/p1.pdf"},
        cfg,
        cast(MCPToolClient, client),
        {},
    )

    assert result == ("p1", None)


# =============================================================================
# _apply_metadata_field (fulltext)
# =============================================================================


def test_apply_metadata_field_fulltext_updates_matching_papers() -> None:
    """Fetched fulltext is written back only for papers present with a hit."""
    metadata = {"p1": {"title": "A"}, "p2": {"title": "B"}}
    results = [
        ("p1", "the full body"),
        ("p2", None),
        ("missing", "orphan content"),
    ]

    count = lr_content._apply_metadata_field(metadata, results, "fulltext")

    assert count == 1
    assert metadata["p1"]["fulltext"] == "the full body"
    assert "fulltext" not in metadata["p2"]


# =============================================================================
# _build_content_runtime_context
# =============================================================================


def test_build_content_runtime_context_carries_research_goal() -> None:
    """The runtime context surfaces the research goal and empty focus areas."""
    state = make_state(research_goal="investigate BRCA1 variants")
    context = lr_content._build_content_runtime_context(state)
    assert context == {
        "research_goal": "investigate BRCA1 variants",
        "focus_areas": [],
    }


# =============================================================================
# _run_content_fetch
# =============================================================================


async def test_run_content_fetch_mixed_success_and_failure() -> None:
    """Parallel content fetch applies successful hits and skips failures."""
    metadata = {
        "p1": {"pdf_url": "http://x/p1.pdf"},
        "p2": {"pdf_url": "http://x/p2.pdf"},
    }
    client = FakeToolResultsClient(
        results={"good_tool": {"content": "body one"}},
        error_tools={"bad_tool"},
    )
    good_cfg = ContentToolConfig(
        mcp_tool_name="good_tool", url_field="pdf_url", content_params={}
    )
    bad_cfg = ContentToolConfig(
        mcp_tool_name="bad_tool", url_field="pdf_url", content_params={}
    )
    papers_needing_content = [
        ("p1", metadata["p1"], good_cfg),
        ("p2", metadata["p2"], bad_cfg),
    ]

    count = await lr_content._run_content_fetch(
        papers_needing_content, cast(MCPToolClient, client), {}, metadata
    )

    assert count == 1
    assert metadata["p1"]["fulltext"] == "body one"
    assert "fulltext" not in metadata["p2"]


# =============================================================================
# _phase2_5_fetch_content
# =============================================================================


async def test_phase2_5_no_workflow_is_noop() -> None:
    """With no workflow configured, content config is empty and no-op."""
    metadata = {"p1": {"pdf_url": "http://x/p1.pdf"}}
    client = make_tool_results_client()
    state = make_state(research_goal="goal")

    await lr_content._phase2_5_fetch_content(
        metadata, {}, make_search_config(), client, state
    )

    assert "fulltext" not in metadata["p1"]
    assert cast(FakeToolResultsClient, client).calls == []


async def test_phase2_5_no_eligible_papers_is_noop() -> None:
    """A configured content tool with nothing eligible makes no calls."""
    workflow = WorkflowConfig(
        content_tool="content", content_url_field="pdf_url"
    )
    registry = _registry(
        {"content": ToolConfig(server="s", mcp_tool_name="mcp_content")}
    )
    metadata = {
        "p1": {"pdf_url": "http://x.pdf", "fulltext": "already have it"}
    }
    client = make_tool_results_client()
    state = make_state(research_goal="goal")

    await lr_content._phase2_5_fetch_content(
        metadata,
        {},
        make_search_config(workflow=workflow, tool_registry=registry),
        client,
        state,
    )

    assert cast(FakeToolResultsClient, client).calls == []


async def test_phase2_5_success_populates_fulltext() -> None:
    """An eligible paper gets its fulltext fetched and written back."""
    workflow = WorkflowConfig(
        content_tool="content", content_url_field="pdf_url"
    )
    registry = _registry(
        {"content": ToolConfig(server="s", mcp_tool_name="mcp_content")}
    )
    metadata = {"p1": {"pdf_url": "http://x/p1.pdf"}}
    client = make_tool_results_client(
        results={"mcp_content": {"content": "fetched body"}}
    )
    state = make_state(research_goal="goal")

    await lr_content._phase2_5_fetch_content(
        metadata,
        {},
        make_search_config(workflow=workflow, tool_registry=registry),
        client,
        state,
    )

    assert metadata["p1"]["fulltext"] == "fetched body"


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


class _StubRegistry:
    """Minimal ``ToolRegistry`` stand-in for ``get_workflow``/``get_tool``."""

    def __init__(
        self,
        workflow: WorkflowConfig,
        tools: dict[str, ToolConfig] | None = None,
    ) -> None:
        """Store the workflow ``get_workflow`` returns and the tool map.

        Args:
            workflow: The ``WorkflowConfig`` returned for the
                ``"literature_review"`` workflow name.
            tools: Tool-id -> ToolConfig map ``get_tool`` resolves.
        """
        self._workflow = workflow
        self._tools = tools or {}

    def get_workflow(self, name: str) -> WorkflowConfig | None:
        """Return the configured workflow for ``"literature_review"``."""
        return self._workflow if name == "literature_review" else None

    def get_tool(self, tool_id: str) -> ToolConfig | None:
        """Resolve a tool id to its configured ToolConfig, or None."""
        return self._tools.get(tool_id)


def test_get_search_config_multi_source_logs_sources_and_defaults_pubmed() -> (
    None
):
    """Multi-source mode still defaults Phase 1's fallback tool to pubmed.

    Per-source tool resolution happens later, in Phase 2; only the enabled
    (non-disabled) search sources are logged here.
    """
    workflow = WorkflowConfig(
        search_sources=[
            SearchSourceConfig(tool="src_a"),
            SearchSourceConfig(tool="src_b", enabled=False),
        ]
    )
    registry = _StubRegistry(workflow)
    state = make_state(tool_registry=cast(ToolRegistry, registry))

    config = run_config.search_config_for(state)

    assert config.is_multi_source is True
    assert config.search_tool_name == "pubmed_search_with_fulltext"
    assert config.source_name == "pubmed"
    assert config.search_tool_config is None


def test_get_search_config_single_source_resolves_configured_tool() -> None:
    """A configured, resolvable ``primary_search`` tool drives Phase 1."""
    tool_config = ToolConfig(
        server="s", mcp_tool_name="pubmed_ft", source_type="academic"
    )
    workflow = WorkflowConfig(primary_search="pubmed_primary")
    registry = _StubRegistry(workflow, {"pubmed_primary": tool_config})
    state = make_state(tool_registry=cast(ToolRegistry, registry))

    config = run_config.search_config_for(state)

    assert config.is_multi_source is False
    assert config.search_tool_name == "pubmed_ft"
    assert config.source_name == "academic"
    assert config.search_tool_config is tool_config
