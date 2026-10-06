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
    _make_event_recorder,
    _stub_node,
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
