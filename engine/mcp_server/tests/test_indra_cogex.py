import logging
from typing import Any

import httpx
import pytest
from mcp_server.tests._httpx import (
    stub_failure,
    stub_responses,
)
from mcp_server.tools.indra_cogex import (
    query_drug_info,
    query_gene_codependents,
    query_gene_disease_network,
    query_pathways,
    run_enrichment_analysis,
)

_ROWS = [{"x": 1}]
_KRAS = ["HGNC", "6407"]
_METFORMIN = ["CHEBI", "CHEBI:27690"]

# Independent expected mappings still detect changes to the production
# dispatch table: (tool, kwargs, endpoint, payload sent, result returned).
_DISPATCH = [
    pytest.param(
        query_gene_disease_network,
        {"identifier": "MESH:D000544", "entity_type": "disease"},
        "/api/get_genes_for_disease",
        {"disease": ["MESH", "D000544"]},
        {"genes": _ROWS, "total_genes": 1},
        id="network disease to genes",
    ),
    pytest.param(
        query_gene_codependents,
        {"gene_id": "HGNC:6407"},
        "/api/get_codependents_for_gene",
        {"gene": _KRAS},
        {"codependent_genes": _ROWS, "total_codependents": 1},
        id="codependents",
    ),
    pytest.param(
        query_drug_info,
        {"identifier": "CHEBI:CHEBI:27690", "query_type": "targets"},
        "/api/get_targets_for_drug",
        {"drug": _METFORMIN},
        {"targets": _ROWS, "total_targets": 1},
        id="drug targets",
    ),
    pytest.param(
        run_enrichment_analysis,
        {
            "gene_list": ["HGNC:1"],
            "analysis_type": "signed",
            "negative_genes": ["HGNC:2"],
        },
        "/api/signed_analysis",
        {"positive_genes": ["HGNC:1"], "negative_genes": ["HGNC:2"]},
        {"results": _ROWS},
        id="signed enrichment",
    ),
    pytest.param(
        query_pathways,
        {"gene_ids": ["HGNC:6407", "HGNC:1097"]},
        "/api/get_shared_pathways_for_genes",
        {"genes": [_KRAS, ["HGNC", "1097"]]},
        {"pathways": _ROWS, "total_pathways": 1},
        id="pathways shared by genes",
    ),
]


@pytest.mark.parametrize(("tool", "kwargs", "endpoint", "payload", "expected"), _DISPATCH)
async def test_tool_calls_reach_their_endpoint_and_shape_the_result(
    monkeypatch: pytest.MonkeyPatch,
    tool: Any,
    kwargs: dict[str, Any],
    endpoint: str,
    payload: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    client = stub_responses(monkeypatch, _ROWS)

    result = await tool(**kwargs)

    url, sent = client.calls[0]
    assert url.endswith(endpoint)
    assert {key: sent[key] for key in payload} == payload
    assert {key: result[key] for key in expected} == expected


@pytest.mark.parametrize(
    ("tool", "kwargs"),
    list({case.values[0]: case.values[:2] for case in _DISPATCH}.values()),
)
async def test_every_tool_degrades_on_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tool: Any,
    kwargs: dict[str, Any],
) -> None:
    stub_failure(monkeypatch, httpx.ConnectError("connection refused"))

    with caplog.at_level(logging.ERROR):
        result = await tool(**kwargs)

    assert set(result) == {"error", "query"}
    assert "connection refused" in result["error"]
    assert isinstance(result["query"], dict)
    assert f"{tool.__name__} failed: connection refused" in caplog.text
