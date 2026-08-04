"""Tests for INDRA mechanistic statement queries.

Unlike the other CoGex tool families, the MeSH-term and agent query paths
here build genuinely different payloads (a fixed shape vs. several optional
filters), so they are written out as separate tests rather than forced into
one parametrization.
"""

import pytest
from mcp_server.tests._httpx import stub_responses, stub_unreachable
from mcp_server.tools.indra_cogex.statements import (
    query_mechanistic_statements,
)


async def test_statements_by_mesh_term_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = stub_responses(monkeypatch, [{"stmt": "Activation"}])

    result = await query_mechanistic_statements(mesh_term="MESH:D002289")

    assert result["statements"] == [{"stmt": "Activation"}]
    assert result["total_statements"] == 1
    assert result["query"] == {
        "agent": None,
        "other_agent": None,
        "mesh_term": "MESH:D002289",
        "relation_types": None,
    }
    call_url, call_payload = client.calls[0]
    assert call_url.endswith("/api/get_stmts_for_mesh")
    assert call_payload["mesh_term"] == ["MESH", "D002289"]
    assert call_payload["include_child_terms"] is True


async def test_statements_by_agent_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = stub_responses(monkeypatch, [{"stmt": "Inhibition"}])

    result = await query_mechanistic_statements(agent="KRAS")

    assert result["statements"] == [{"stmt": "Inhibition"}]
    call_url, call_payload = client.calls[0]
    assert call_url.endswith("/api/get_statements")
    # A plain name is sent as-is rather than parsed into a CURIE.
    assert call_payload["agent"] == "KRAS"
    assert "other_agent" not in call_payload
    assert "rel_types" not in call_payload
    assert "agent_role" not in call_payload


async def test_statements_by_agent_includes_only_given_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = stub_responses(monkeypatch, [])

    await query_mechanistic_statements(
        agent="HGNC:6407",
        other_agent="HGNC:1097",
        relation_types=["Activation"],
        agent_role="subject",
    )

    _, call_payload = client.calls[0]
    assert call_payload["agent"] == ["HGNC", "6407"]
    assert call_payload["other_agent"] == ["HGNC", "1097"]
    assert call_payload["rel_types"] == ["Activation"]
    assert call_payload["agent_role"] == "subject"


async def test_statements_requires_agent_or_mesh_term(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_unreachable(monkeypatch)

    result = await query_mechanistic_statements()

    assert result == {
        "error": "provide either 'agent' or 'mesh_term'",
        "query": {
            "agent": None,
            "other_agent": None,
            "mesh_term": None,
            "relation_types": None,
        },
    }


async def test_statements_reports_a_malformed_mesh_term(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_unreachable(monkeypatch)

    result = await query_mechanistic_statements(mesh_term="no-colon")

    assert result["query"]["mesh_term"] == "no-colon"
    assert "invalid identifier" in result["error"]
