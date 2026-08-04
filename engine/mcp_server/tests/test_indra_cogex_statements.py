"""Tests for INDRA mechanistic statement queries.

Unlike the other CoGex tool families, the MeSH-term and agent query paths
here build genuinely different payloads (a fixed shape vs. several optional
filters), so they are written out as separate tests rather than forced into
one parametrization.
"""

from typing import Any

import httpx
import pytest
from mcp_server.tools.indra_cogex.statements import (
    query_mechanistic_statements,
)


class _StubResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        """Represent a 2xx response: never raises."""

    def json(self) -> Any:
        """Return the fixture payload."""
        return self._payload


class _StubClient:
    def __init__(
        self, payload: Any = None, error: Exception | None = None
    ) -> None:
        self._payload = payload
        self._error = error
        self.calls: list[tuple[str, Any]] = []

    async def __aenter__(self) -> "_StubClient":
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False

    async def post(self, url: str, json: Any = None) -> _StubResponse:
        self.calls.append((url, json))
        if self._error is not None:
            raise self._error
        return _StubResponse(self._payload)


def _stub(monkeypatch: pytest.MonkeyPatch, payload: Any) -> _StubClient:
    client = _StubClient(payload=payload)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)
    return client


def _stub_unreachable(monkeypatch: pytest.MonkeyPatch, message: str) -> None:
    client = _StubClient(error=RuntimeError(message))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)


async def test_statements_by_mesh_term_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _stub(monkeypatch, [{"stmt": "Activation"}])

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
    client = _stub(monkeypatch, [{"stmt": "Inhibition"}])

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
    client = _stub(monkeypatch, [])

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
    _stub_unreachable(monkeypatch, "must not reach the network")

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
    _stub_unreachable(monkeypatch, "must not reach the network")

    result = await query_mechanistic_statements(mesh_term="no-colon")

    assert result["query"]["mesh_term"] == "no-colon"
    assert "invalid identifier" in result["error"]
