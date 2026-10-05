from __future__ import annotations

from typing import Any

import pytest

from co_scientist.agents.generation.literature_review import (
    literature_review_node,
)
from co_scientist.agents.generation.literature_review import node as lr
from co_scientist.constants import LITERATURE_REVIEW_FAILED
from tests._llm_fake import install_fake_llm
from tests._research_fakes import (
    _TWO_PAPERS,
    _make_event_recorder,
    _RaisingClient,
    _stub_node,
    _stub_research,
)
from tests._state import make_state


async def test_an_unreachable_server_fails_the_review_and_records_degradation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A setup-time outage routes around this node; an outage here must mark
    report degradation."""
    fake_client = _stub_node(monkeypatch, server_available=False)
    state = make_state(research_goal="cancer immunotherapy resistance")
    state["context_enrichment_sources"] = [{"title": "an attachment"}]

    result = await literature_review_node(state)

    assert result["articles_with_reasoning"] == LITERATURE_REVIEW_FAILED
    assert result["literature_review_queries"] == []
    assert result["articles"] == []
    assert result["messages"][0]["metadata"]["error"] is True
    assert fake_client.calls == []
    degradation = result["retrieval_degradation"]
    assert degradation["reason"] == "mcp_unreachable"
    assert degradation["floor"] == "run_attachments"


async def test_happy_path_populates_synthesis_and_articles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, callback = _make_event_recorder()
    _stub_node(
        monkeypatch,
        server_available=True,
        search_payload=_TWO_PAPERS,
        queries=["query alpha", "query beta"],
        synthesis="SYNTHESIZED REVIEW",
    )
    state = make_state(
        research_goal="immune checkpoint resistance", progress_callback=callback
    )

    result = await literature_review_node(state)

    assert result["articles_with_reasoning"] == "SYNTHESIZED REVIEW"
    assert result["literature_review_queries"] == ["query alpha", "query beta"]
    articles = result["articles"]
    assert len(articles) == 2
    assert {a.source_id for a in articles} == {"PMID1", "PMID2"}
    assert {a.title for a in articles} == {
        "Tumor microenvironment review",
        "Immune checkpoint blockade",
    }
    assert result["messages"][0]["metadata"]["phase"] == "literature_review"
    assert "error" not in result["messages"][0]["metadata"]
    names = [event for event, _ in events]
    assert "literature_review_start" in names
    assert "literature_review_complete" in names


async def test_no_queries_fall_back_to_the_research_goal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_node(
        monkeypatch,
        server_available=True,
        search_payload={"PMID9": {"title": "Single", "fulltext": "Body."}},
        queries=[],
        synthesis="REVIEW",
    )

    result = await literature_review_node(
        make_state(research_goal="rare query fallback goal")
    )

    assert result["literature_review_queries"] == ["rare query fallback goal"]
    assert result["articles_with_reasoning"] == "REVIEW"
    assert len(result["articles"]) == 1


async def test_no_papers_found_returns_failure_with_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_node(
        monkeypatch,
        server_available=True,
        search_payload={},
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


async def test_no_papers_with_search_error_emits_error_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, callback = _make_event_recorder()

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


async def test_research_reaches_the_result_the_run_persists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the result ledger, persisted evidence cannot name the search
    that found it."""
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
    """Downstream code compares the sentinel exactly; appended prose would
    impersonate success."""
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


@pytest.fixture(autouse=True)
def _hermetic_node_model(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_llm(monkeypatch)
