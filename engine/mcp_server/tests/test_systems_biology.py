"""Tests for the STRING, Reactome and Open Targets grounding tools."""

import httpx
import pytest
from mcp_server.tests._httpx import stub_failure, stub_responses
from mcp_server.tools import systems_biology


async def test_string_keeps_the_evidence_channels_apart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A link is reported with its channels, not just a combined score.

    STRING's combined score mixes experimental support with text mining,
    and a pair supported only by co-mention in abstracts is a far weaker
    claim than one with experiments behind it. Collapsing them would let
    a hypothesis cite 0.9 without saying 0.9 of what.
    """
    stub_responses(
        monkeypatch,
        [
            {
                "preferredName_B": "CDK1",
                "stringId_B": "9606.ENSP00000378699",
                "score": 0.998,
                "escore": 0.731,
                "dscore": 0.9,
                "ascore": 0.181,
                "tscore": 0.957,
            }
        ],
    )

    result = await systems_biology.search_string_interactions("WEE1")

    (record,) = result["records"]
    assert result["source"] == "STRING"
    assert record["partner"] == "CDK1"
    assert record["combined_score"] == 0.998
    assert record["experimental_score"] == 0.731
    assert record["textmining_score"] == 0.957


async def test_reactome_resolves_the_entity_before_asking_for_pathways(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pathway membership is a lookup from the entity, not a text search.

    Searching Reactome for "WEE1" finds the reactions and complexes whose
    names match. The question a mechanism needs answered is which
    pathways WEE1 *participates in*, which is a second call keyed by the
    entity id the search resolved.
    """
    client = stub_responses(
        monkeypatch,
        {
            "results": [
                {
                    "entries": [
                        {
                            "stId": "R-HSA-69253",
                            "exactType": "ReferenceGeneProduct",
                        }
                    ]
                }
            ]
        },
        [{"stId": "R-HSA-69478", "displayName": "G2/M DNA replication"}],
    )

    result = await systems_biology.search_reactome_pathways("WEE1")

    (record,) = result["records"]
    assert record["pathway_id"] == "R-HSA-69478"
    assert record["name"] == "G2/M DNA replication"
    # The second request is the entity-keyed one, built from the first.
    assert "R-HSA-69253" in client.calls[1][0]


async def test_reactome_without_a_matching_entity_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unresolvable symbol stops after one call, and says nothing."""
    client = stub_responses(monkeypatch, {"results": []})

    result = await systems_biology.search_reactome_pathways("NOTAGENE")

    assert result["records"] == []
    assert len(client.calls) == 1


async def test_open_targets_reports_only_satisfied_tractability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """False buckets say nothing and are the overwhelming majority.

    Open Targets returns every tractability bucket with a flag. Carrying
    the false ones would spend most of the record telling the model what
    a target is *not*, in a payload it re-sends every turn.
    """
    stub_responses(
        monkeypatch,
        {
            "data": {
                "search": {
                    "hits": [
                        {
                            "id": "ENSG00000166483",
                            "object": {
                                "approvedSymbol": "WEE1",
                                "approvedName": "WEE1 G2 checkpoint kinase",
                                "associatedDiseases": {
                                    "rows": [
                                        {
                                            "score": 0.51,
                                            "disease": {"name": "glioma"},
                                        }
                                    ]
                                },
                                "tractability": [
                                    {
                                        "label": "Approved Drug",
                                        "modality": "SM",
                                        "value": False,
                                    },
                                    {
                                        "label": "Clinical Precedence",
                                        "modality": "SM",
                                        "value": True,
                                    },
                                ],
                            },
                        }
                    ]
                }
            }
        },
    )

    result = await systems_biology.search_open_targets("WEE1")

    (record,) = result["records"]
    assert record["symbol"] == "WEE1"
    assert record["associated_diseases"] == [
        {"disease": "glioma", "score": 0.51}
    ]
    assert record["tractability"] == ["SM: Clinical Precedence"]


@pytest.mark.parametrize(
    ("tool", "source"),
    [
        (systems_biology.search_string_interactions, "STRING"),
        (systems_biology.search_reactome_pathways, "Reactome"),
        (systems_biology.search_open_targets, "Open Targets"),
    ],
)
async def test_a_failed_request_degrades_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch, tool: object, source: str
) -> None:
    """One unreachable source must not fail the step that consults several.

    These are wired into literature-review enrichment and reflection
    alongside four other tools; an exception here would take the whole
    step down over one API's outage.
    """
    stub_failure(monkeypatch, httpx.ConnectError("boom"))

    result = await tool("WEE1")  # type: ignore[operator]

    assert result == {"source": source, "query": "WEE1", "records": []}
