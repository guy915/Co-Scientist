"""Tests for gene-disease-variant and gene codependence CoGex tools."""

import pytest
from mcp_server.tests._httpx import stub_responses, stub_unreachable
from mcp_server.tools.indra_cogex.associations import (
    query_gene_codependents,
    query_gene_disease_network,
)

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
    client = stub_responses(monkeypatch, [{"id": "HGNC:1"}, {"id": "HGNC:2"}])

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
    client = stub_responses(
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
    stub_unreachable(monkeypatch)

    result = await query_gene_disease_network("HGNC:6407", entity_type="bogus")

    assert result == {
        "error": "invalid entity_type 'bogus', use 'disease' or 'gene'",
        "query": {"identifier": "HGNC:6407", "entity_type": "bogus"},
    }


async def test_gene_disease_network_reports_a_malformed_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_unreachable(monkeypatch)

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
    client = stub_responses(
        monkeypatch, [{"gene": "HGNC:2"}, {"gene": "HGNC:3"}]
    )

    result = await query_gene_codependents("HGNC:6407", max_results=1)

    assert result["codependent_genes"] == [{"gene": "HGNC:2"}]
    assert result["total_codependents"] == 2
    assert result["query"] == {"gene_id": "HGNC:6407"}
    call_url, call_payload = client.calls[0]
    assert call_url.endswith("/api/get_codependents_for_gene")
    assert call_payload == {"gene": ["HGNC", "6407"]}
