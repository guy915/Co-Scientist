"""Tests for biological pathway and causal subnetwork CoGex tools.

Neither tool here validates an enum argument (``pathways.py`` does not even
import ``tool_error``), so unlike the other tool families there is no
invalid-choice branch to pin -- only the exception path, driven here by a
malformed identifier.
"""

from typing import Any

import httpx
import pytest
from mcp_server.tools.indra_cogex.pathways import (
    query_causal_subnetwork,
    query_pathways,
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


# --- query_pathways: single-gene vs shared-pathway mode -------------------


@pytest.mark.parametrize(
    "gene_ids,endpoint,payload_key,mode",
    [
        (["HGNC:6407"], "/api/get_pathways_for_gene", "gene", "single"),
        (
            ["HGNC:6407", "HGNC:1097"],
            "/api/get_shared_pathways_for_genes",
            "genes",
            "shared",
        ),
    ],
)
async def test_pathways_success(
    gene_ids: list[str],
    endpoint: str,
    payload_key: str,
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _stub(monkeypatch, [{"pathway": "WP1"}])

    result = await query_pathways(gene_ids)

    assert result["pathways"] == [{"pathway": "WP1"}]
    assert result["total_pathways"] == 1
    # The success path enriches the query with "mode"; this is the one
    # field the exception path (below) does not have, since it is computed
    # inside the coroutine body rather than by the public wrapper.
    assert result["query"] == {"gene_ids": gene_ids, "mode": mode}
    call_url, call_payload = client.calls[0]
    assert call_url.endswith(endpoint)
    assert payload_key in call_payload


async def test_pathways_reports_a_malformed_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_unreachable(monkeypatch, "must not reach the network")

    result = await query_pathways(["HGNC:6407", "no-colon"])

    # The exception path's query comes from the public wrapper, so it has
    # no "mode" key -- only the success path adds one.
    assert result["query"] == {"gene_ids": ["HGNC:6407", "no-colon"]}
    assert "invalid identifier" in result["error"]


# --- query_causal_subnetwork: mediated vs direct relations ---------------


@pytest.mark.parametrize(
    "find_mediators,endpoint,payload_flag",
    [
        (True, "/api/indra_mediated_subnetwork", "order_by_ev_count"),
        (False, "/api/indra_subnetwork_relations", "include_db_evidence"),
    ],
)
async def test_causal_subnetwork_success(
    find_mediators: bool,
    endpoint: str,
    payload_flag: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _stub(monkeypatch, [{"stmt": "Activation"}])

    result = await query_causal_subnetwork(
        ["HGNC:6407", "HGNC:5173"], find_mediators=find_mediators
    )

    assert result["subnetwork"] == [{"stmt": "Activation"}]
    assert result["total_relations"] == 1
    assert result["query"]["find_mediators"] == find_mediators
    call_url, call_payload = client.calls[0]
    assert call_url.endswith(endpoint)
    assert call_payload[payload_flag] is True


async def test_causal_subnetwork_reports_a_malformed_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_unreachable(monkeypatch, "must not reach the network")

    result = await query_causal_subnetwork(["HGNC:6407", "bad-node"])

    assert result["query"] == {"node_ids": ["HGNC:6407", "bad-node"]}
    assert "invalid identifier" in result["error"]
