"""Tests for ``literature_review_node`` orchestration.

The leaf helpers in ``literature_review.helpers`` are covered by
``test_literature_review_helpers_*`` and the in-file pure functions by
``test_literature_review_pure``; here we exercise the node's orchestration
along its fallback, happy, and edge-case paths.

External seams stubbed (each bound on the submodule that consumes it):

* ``node.get_node_cache`` -> a no-op cache (always miss / no-op set), so the
  global on-disk node cache never interferes and tests stay deterministic.
* ``node.check_literature_source_available`` -> bool, the MCP-gate the node
  consults before doing any work; ``False`` drives the unavailable fallback,
  ``True`` the happy path (without it the node would dial ``localhost:8888``).
* ``node.get_mcp_client`` -> a fake whose ``call_tool`` returns canned search
  papers, standing in for the real MCP search/tool path.
* ``call_llm_json`` -> shared by query-generation (``queries``, returns
  ``queries``) and per-paper analysis (``analysis``, the dict is stored opaquely
  and fed to synthesis), so it is stubbed on both submodules.
* ``synthesis.call_llm`` -> phase-4 synthesis text (prompt saving lives inside
  the real LLM wrappers now, so stubbing them also keeps prompt files off disk).

With ``tool_registry=None`` the multi-source/PDF-discovery/content-fetch/
context-enrichment phases (2.4/2.5/2.6) all early-return, so the node runs in
its real single-source, LLM-only orchestration.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from co_scientist.constants import LITERATURE_REVIEW_FAILED
from co_scientist.nodes.literature_review import analysis as lr_analysis
from co_scientist.nodes.literature_review import literature_review_node
from co_scientist.nodes.literature_review import node as lr
from co_scientist.nodes.literature_review import queries as lr_queries
from co_scientist.nodes.literature_review import synthesis as lr_synthesis
from tests._state import make_state


class _NoOpNodeCache:
    """A node cache that never hits and never writes.

    Substituted for the global on-disk ``NodeCache`` so orchestration tests
    neither read stale results nor leave pickles behind.
    """

    def get(self, *_: Any, **__: Any) -> None:
        """Always miss."""
        return None

    def set(self, *_: Any, **__: Any) -> None:
        """No-op store."""
        return None


class _FakeMCPClient:
    """Minimal stand-in for ``MCPToolClient`` used by the node.

    ``call_tool`` returns a fixed payload regardless of tool name/args; the node
    only uses it for searching here (query generation falls back to the stubbed
    LLM, and the no-registry path disables every other tool phase).
    """

    def __init__(self, search_payload: dict[str, dict[str, Any]]) -> None:
        """Store the dict that every ``call_tool`` invocation returns.

        Args:
            search_payload: The ``{paper_id: metadata}`` dict returned for any
                tool call (passed through unchanged by ``normalize_search_
                response`` when there is no tool config).
        """
        self._search_payload = search_payload
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Record the call and return the canned search payload."""
        self.calls.append((tool_name, kwargs))
        return self._search_payload

    def has_tool(self, _tool_name: str) -> bool:
        """No enrichment tools are exposed by the fake client."""
        return False


def _stub_node(
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_available: bool,
    search_payload: dict[str, dict[str, Any]] | None = None,
    queries: list[str] | None = None,
    synthesis: str = "SYNTHESIZED REVIEW",
) -> _FakeMCPClient:
    """Patch every external seam of ``literature_review_node``.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        source_available: Value returned by ``check_literature_source_
            available``.
        search_payload: ``{paper_id: metadata}`` the fake MCP client returns
            from ``call_tool``.
        queries: Queries returned by the stubbed query-generation LLM. Defaults
            to a single query.
        synthesis: Text returned by the stubbed synthesis ``call_llm``.

    Returns:
        The ``_FakeMCPClient`` instance wired into the node (so the test can
        inspect ``.calls``).
    """
    fake_client = _FakeMCPClient(search_payload or {})

    monkeypatch.setattr(lr, "get_node_cache", lambda: _NoOpNodeCache())

    async def fake_available(**_: Any) -> bool:
        return source_available

    monkeypatch.setattr(lr, "check_literature_source_available", fake_available)

    async def fake_get_client(**_: Any) -> _FakeMCPClient:
        return fake_client

    monkeypatch.setattr(lr, "get_mcp_client", fake_get_client)

    async def fake_llm_json(**_: Any) -> dict[str, Any]:
        # Shared by query-generation (reads "queries") and paper analysis
        # (stores the whole dict opaquely for synthesis).
        return {"queries": queries if queries is not None else ["query one"]}

    monkeypatch.setattr(lr_queries, "call_llm_json", fake_llm_json)
    monkeypatch.setattr(lr_analysis, "call_llm_json", fake_llm_json)

    async def fake_llm(**_: Any) -> str:
        return synthesis

    monkeypatch.setattr(lr_synthesis, "call_llm", fake_llm)

    return fake_client


def _make_event_recorder() -> tuple[
    list[tuple[str, dict[str, Any]]],
    Callable[[str, dict[str, Any]], Awaitable[None]],
]:
    """Build a progress callback that records (event, payload) tuples.

    Returns:
        A tuple of the (initially empty) recorded-events list and the async
        callback that appends to it; pass the callback as ``progress_callback``
        and inspect the list afterwards.
    """
    events: list[tuple[str, dict[str, Any]]] = []

    async def callback(event: str, payload: dict[str, Any]) -> None:
        events.append((event, payload))

    return events, callback


# =============================================================================
# No-MCP / source-unavailable fallback
# =============================================================================


async def test_source_unavailable_returns_failure_without_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the literature source is unavailable the node fails fast.

    It returns the documented failure result (``articles_with_reasoning`` set to
    the failure sentinel, empty queries/articles) and never touches the MCP
    search client.
    """
    fake_client = _stub_node(monkeypatch, source_available=False)
    state = make_state(research_goal="cancer immunotherapy resistance")

    result = await literature_review_node(state)

    assert result["articles_with_reasoning"] == LITERATURE_REVIEW_FAILED
    assert result["literature_review_queries"] == []
    assert result["articles"] == []
    assert result["messages"][0]["metadata"]["error"] is True
    # The search seam was never reached.
    assert fake_client.calls == []


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
    papers = {
        "PMID1": {
            "title": "Tumor microenvironment review",
            "authors": ["Smith J"],
            "year": "2021",
            "fulltext": "Full body one.",
            "abstract": "Abstract one.",
        },
        "PMID2": {
            "title": "Immune checkpoint blockade",
            "authors": ["Doe A"],
            "year": "2022",
            "fulltext": "Full body two.",
            "abstract": "Abstract two.",
        },
    }
    _stub_node(
        monkeypatch,
        source_available=True,
        search_payload=papers,
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
        source_available=True,
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
        source_available=True,
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
        source_available=True,
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
        source_available=True,
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
        monkeypatch, source_available=True, search_payload={}, queries=["q"]
    )

    class _RaisingClient:
        async def call_tool(self, _tool_name: str, **_: Any) -> Any:
            raise ConnectionError("All connection attempts failed")

        def has_tool(self, _tool_name: str) -> bool:
            return False

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
        monkeypatch, source_available=True, search_payload={}, queries=["q"]
    )
    state = make_state(
        research_goal="genuinely empty goal", progress_callback=callback
    )
    await literature_review_node(state)

    empty_payloads = [p for e, p in events if e == "literature_review_empty"]
    assert empty_payloads, "expected a literature_review_empty event"
    assert empty_payloads[0]["search_errors_count"] == 0
