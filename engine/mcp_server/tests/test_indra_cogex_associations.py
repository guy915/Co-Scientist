"""Tests for gene-disease-variant and gene codependence CoGex tools."""

from typing import Any

import httpx
import pytest
from mcp_server.tools.indra_cogex.associations import (
    query_gene_codependents,
    query_gene_disease_network,
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
    """Serves queued responses in call order, or raises once configured."""

    def __init__(
        self,
        responses: list[Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._responses = list(responses) if responses else []
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
        return _StubResponse(self._responses.pop(0))


def _stub(monkeypatch: pytest.MonkeyPatch, *payloads: Any) -> _StubClient:
    client = _StubClient(responses=list(payloads))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)
    return client


def _stub_unreachable(monkeypatch: pytest.MonkeyPatch, message: str) -> None:
    client = _StubClient(error=RuntimeError(message))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)


# --- query_gene_disease_network: success, parametrized over direction ---


@pytest.mark.parametrize(
    "entity_type,endpoint,result_key,total_key",
    [
        ("disease", "/api/get_genes_for_disease", "genes", "total_genes"),
        ("gene", "/api/get_diseases_for_gene", "diseases", "total_diseases"),
    ],
)
async def test_gene_disease_network_success(
    entity_type: str,
    endpoint: str,
    result_key: str,
    total_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _stub(monkeypatch, [{"id": "HGNC:1"}, {"id": "HGNC:2"}])

    result = await query_gene_disease_network(
        "MESH:D000544", entity_type=entity_type
    )

    assert result[result_key] == [{"id": "HGNC:1"}, {"id": "HGNC:2"}]
    assert result[total_key] == 2
    assert result["query"] == {
        "identifier": "MESH:D000544",
        "entity_type": entity_type,
    }
    assert client.calls[0][0].endswith(endpoint)


async def test_gene_disease_network_includes_variants_as_a_second_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _stub(
        monkeypatch,
        [{"id": "HGNC:1"}],  # genes
        [{"rsid": "rs1"}],  # variants
    )

    result = await query_gene_disease_network(
        "MESH:D000544", entity_type="disease", include_variants=True
    )

    assert result["genes"] == [{"id": "HGNC:1"}]
    assert result["variants"] == [{"rsid": "rs1"}]
    assert result["total_variants"] == 1
    assert len(client.calls) == 2
    assert client.calls[0][0].endswith("/api/get_genes_for_disease")
    assert client.calls[1][0].endswith("/api/get_variants_for_disease")


async def test_gene_disease_network_rejects_invalid_entity_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_unreachable(monkeypatch, "must not reach the network")

    result = await query_gene_disease_network("HGNC:6407", entity_type="bogus")

    assert result == {
        "error": "invalid entity_type 'bogus', use 'disease' or 'gene'",
        "query": {"identifier": "HGNC:6407", "entity_type": "bogus"},
    }


async def test_gene_disease_network_reports_a_malformed_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_unreachable(monkeypatch, "must not reach the network")

    result = await query_gene_disease_network("not-a-curie", entity_type="gene")

    assert result["query"] == {
        "identifier": "not-a-curie",
        "entity_type": "gene",
    }
    assert "invalid identifier" in result["error"]


# --- query_gene_codependents: single shape, not parametrized -------------


async def test_gene_codependents_success_and_caps_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _stub(monkeypatch, [{"gene": "HGNC:2"}, {"gene": "HGNC:3"}])

    result = await query_gene_codependents("HGNC:6407", max_results=1)

    assert result["codependent_genes"] == [{"gene": "HGNC:2"}]
    assert result["total_codependents"] == 2
    assert result["query"] == {"gene_id": "HGNC:6407"}
    call_url, call_payload = client.calls[0]
    assert call_url.endswith("/api/get_codependents_for_gene")
    assert call_payload == {"gene": ["HGNC", "6407"]}
