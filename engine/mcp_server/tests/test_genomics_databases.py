"""Tests for the Ensembl and gnomAD gene-level lookups."""

import httpx
import pytest
from mcp_server.tests._httpx import stub_failure, stub_responses
from mcp_server.tools import genomics_databases


async def test_ensembl_carries_the_stable_identifier_and_locus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A symbol is resolved to something that does not get reused.

    Gene symbols are renamed and reused; Ensembl ids are not. A
    hypothesis built on "WEE1" and one built on ENSG00000166483 are the
    same claim only if the resolution happened.
    """
    stub_responses(
        monkeypatch,
        {
            "id": "ENSG00000166483",
            "display_name": "WEE1",
            "biotype": "protein_coding",
            "description": "WEE1 G2 checkpoint kinase",
            "seq_region_name": "11",
            "start": 9573540,
            "end": 9593457,
            "strand": 1,
        },
    )

    result = await genomics_databases.search_ensembl_gene("WEE1")

    (record,) = result["records"]
    assert record["ensembl_id"] == "ENSG00000166483"
    assert record["locus"] == "11:9573540-9593457"
    assert record["biotype"] == "protein_coding"


async def test_gnomad_carries_the_direction_each_number_runs_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The constraint numbers are meaningless without their conventions.

    pLI near 1 means intolerant while LOEUF *below* 0.35 means
    constrained, so the two headline metrics run in opposite directions.
    A model handed a bare 0.35 cannot tell which it is looking at, and a
    hypothesis that reads it backwards is confidently wrong.
    """
    stub_responses(
        monkeypatch,
        {
            "data": {
                "gene": {
                    "gene_id": "ENSG00000166483",
                    "symbol": "WEE1",
                    "gnomad_constraint": {
                        "pli": 0.99,
                        "oe_lof": 0.23,
                        "oe_lof_upper": 0.35,
                        "mis_z": 2.57,
                    },
                }
            }
        },
    )

    result = await genomics_databases.search_gnomad_constraint("WEE1")

    (record,) = result["records"]
    assert record["pli"] == 0.99
    assert record["loeuf"] == 0.35
    assert "LOEUF (loeuf) below 0.35" in record["interpretation"]


async def test_a_gene_without_constraint_data_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gene gnomAD has no constraint for says nothing, not zero.

    Returning a record of ``None`` values would read as "unconstrained",
    which is the opposite of "not measured".
    """
    stub_responses(
        monkeypatch,
        {"data": {"gene": {"gene_id": "ENSG1", "gnomad_constraint": None}}},
    )

    result = await genomics_databases.search_gnomad_constraint("XYZ")

    assert result["records"] == []


@pytest.mark.parametrize(
    ("tool", "source"),
    [
        (genomics_databases.search_ensembl_gene, "Ensembl"),
        (genomics_databases.search_gnomad_constraint, "gnomAD"),
    ],
)
async def test_a_failed_request_degrades_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch, tool: object, source: str
) -> None:
    """One unreachable source must not fail a step consulting several."""
    stub_failure(monkeypatch, httpx.ConnectError("boom"))

    result = await tool("WEE1")  # type: ignore[operator]

    assert result == {"source": source, "query": "WEE1", "records": []}
