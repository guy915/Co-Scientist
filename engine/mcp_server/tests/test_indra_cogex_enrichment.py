"""Tests for gene set enrichment analysis via INDRA CoGex."""

from typing import Any

import pytest
from mcp_server.tests._httpx import stub_responses, stub_unreachable
from mcp_server.tools.indra_cogex.enrichment import run_enrichment_analysis

# --- run_enrichment_analysis: discrete / signed / kinase ------------------
# The three analysis types share one request/response shape closely enough
# to parametrize, aside from "signed" needing an extra argument -- captured
# below as per-case extra kwargs rather than forcing a shared signature.


@pytest.mark.parametrize(
    "analysis_type,extra_kwargs,endpoint,gene_key",
    [
        ("discrete", {}, "/api/discrete_analysis", "gene_list"),
        (
            "signed",
            {"negative_genes": ["HGNC:2"]},
            "/api/signed_analysis",
            "positive_genes",
        ),
        ("kinase", {}, "/api/kinase_analysis", "phosphosite_list"),
    ],
)
async def test_enrichment_success(
    analysis_type: str,
    extra_kwargs: dict[str, Any],
    endpoint: str,
    gene_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = stub_responses(monkeypatch, {"p_value": 0.01})

    result = await run_enrichment_analysis(
        ["HGNC:1"], analysis_type=analysis_type, **extra_kwargs
    )

    assert result["results"] == {"p_value": 0.01}
    assert result["query"] == {
        "analysis_type": analysis_type,
        "gene_count": 1,
    }
    call_url, call_payload = client.calls[0]
    assert call_url.endswith(endpoint)
    assert gene_key in call_payload


async def test_enrichment_rejects_invalid_analysis_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_unreachable(monkeypatch)

    result = await run_enrichment_analysis(["HGNC:1"], analysis_type="bogus")

    assert result == {
        "error": "invalid analysis_type 'bogus', use: discrete, signed, kinase",
        "query": {"analysis_type": "bogus", "gene_count": 1},
    }


async def test_enrichment_signed_requires_negative_genes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_unreachable(monkeypatch)

    result = await run_enrichment_analysis(["HGNC:1"], analysis_type="signed")

    assert result == {
        "error": "signed analysis requires 'negative_genes'",
        "query": {"analysis_type": "signed", "gene_count": 1},
    }
