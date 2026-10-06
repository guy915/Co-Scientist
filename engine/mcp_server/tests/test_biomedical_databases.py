import logging
from typing import Any

import httpx
import mcp_server.tools.biomedical_databases as databases
import pytest
from mcp_server.tests._httpx import (
    registered_tools,
    stub_failure,
    stub_responses,
    transport_responses,
)


@pytest.mark.parametrize(
    "tool_case",
    [
        {
            "tool_name": "search_chembl",
            "query": "aspirin",
            "source": "ChEMBL",
            "success_payload": {
                "molecules": [
                    {"molecule_chembl_id": "CHEMBL25", "pref_name": "ASPIRIN"}
                ]
            },
            "record": {"chembl_id": "CHEMBL25"},
        },
        {
            "tool_name": "search_uniprot",
            "query": "EGFR",
            "source": "UniProtKB/Swiss-Prot",
            "success_payload": {
                "results": [
                    {
                        "primaryAccession": "P00533",
                        "genes": [{"geneName": {"value": "EGFR"}}],
                        "comments": [
                            {
                                "commentType": "FUNCTION",
                                "texts": [{"value": "Kinase."}],
                            }
                        ],
                    }
                ]
            },
            "record": {
                "accession": "P00533",
                "gene": "EGFR",
                "functions": ["Kinase."],
            },
        },
    ],
)
async def test_registered_biomedical_tools_report_outcome_at_mcp_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tool_case: dict[str, Any],
) -> None:
    tool_name = tool_case["tool_name"]
    query = tool_case["query"]
    envelope = {"source": tool_case["source"], "query": query, "records": []}
    requests = transport_responses(
        monkeypatch,
        httpx.Response(200, json=tool_case["success_payload"]),
        httpx.Response(200, json={"molecules": [], "results": []}),
        httpx.Response(503, json={}),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={}),
        httpx.ReadTimeout("upstream timeout"),
        httpx.ConnectError("connection refused"),
    )

    async with registered_tools() as client:
        tool_names = {tool.name for tool in await client.list_tools()}
        results = [
            await client.call_tool(tool_name, {"query": query})
            for _ in range(7)
        ]

    success, empty, *failures = results
    assert tool_name in tool_names
    assert {
        key: success.data["records"][0][key] for key in tool_case["record"]
    } == tool_case["record"]
    assert "error" not in success.data
    assert empty.data == envelope
    assert [failure.data for failure in failures] == [
        envelope | {"error": error}
        for error in (
            {"kind": "http_status", "status_code": 503},
            {"kind": "invalid_response"},
            {"kind": "invalid_response"},
            {"kind": "timeout"},
            {"kind": "network_error"},
        )
    ]
    assert all(result.is_error is not True for result in results)
    assert len(requests) == 7


def _study(**overrides: object) -> dict[str, object]:
    status: dict[str, object] = {
        "overallStatus": "TERMINATED",
        "whyStopped": "Insufficient efficacy",
        "startDateStruct": {"date": "2015-03"},
    }
    status.update(overrides)
    return {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT01827384",
                "briefTitle": "Adavosertib in TP53-mutant tumours",
            },
            "statusModule": status,
            "designModule": {
                "phases": ["PHASE2"],
                "enrollmentInfo": {"count": 208},
            },
            "conditionsModule": {"conditions": ["Solid Tumour"]},
            "armsInterventionsModule": {
                "interventions": [{"name": "Adavosertib"}]
            },
        }
    }


async def test_a_terminated_trial_reports_why_it_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_responses(monkeypatch, {"studies": [_study()]})

    result = await databases.search_clinical_trials("adavosertib")

    (record,) = result["records"]
    assert record["nct_id"] == "NCT01827384"
    assert record["status"] == "TERMINATED"
    assert record["why_stopped"] == "Insufficient efficacy"
    assert record["interventions"] == ["Adavosertib"]


async def test_a_study_missing_modules_is_ordinary_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_responses(
        monkeypatch,
        {"studies": [{"protocolSection": {"identificationModule": {}}}]},
    )

    result = await databases.search_clinical_trials("nothing")

    (record,) = result["records"]
    assert record["status"] is None
    assert record["interventions"] == []


async def test_ensembl_carries_the_stable_identifier_and_locus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_responses(
        monkeypatch,
        {
            "id": "ENSG00000166483",
            "display_name": "WEE1",
            "biotype": "protein_coding",
            "seq_region_name": "11",
            "start": 9573540,
            "end": 9593457,
            "strand": 1,
        },
    )

    result = await databases.search_ensembl_gene("WEE1")

    (record,) = result["records"]
    assert record["ensembl_id"] == "ENSG00000166483"
    assert record["locus"] == "11:9573540-9593457"
    assert record["biotype"] == "protein_coding"


async def test_gnomad_carries_the_direction_each_number_runs_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pLI near 1 means intolerant; LOEUF below 0.35 means constrained, in
    the opposite direction."""
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

    result = await databases.search_gnomad_constraint("WEE1")

    (record,) = result["records"]
    assert record["pli"] == 0.99
    assert record["loeuf"] == 0.35
    assert "LOEUF (loeuf) below 0.35" in record["interpretation"]


async def test_a_gene_without_constraint_data_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unmeasured constraint is not evidence of an unconstrained gene."""
    stub_responses(
        monkeypatch,
        {"data": {"gene": {"gene_id": "ENSG1", "gnomad_constraint": None}}},
    )

    result = await databases.search_gnomad_constraint("XYZ")

    assert result["records"] == []


async def test_string_keeps_the_evidence_channels_apart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """STRING combines experiments with text mining; high co-mention scores
    are weaker evidence."""
    stub_responses(
        monkeypatch,
        [
            {
                "preferredName_B": "CDK1",
                "stringId_B": "9606.ENSP00000378699",
                "score": 0.998,
                "escore": 0.731,
                "tscore": 0.957,
            }
        ],
    )

    result = await databases.search_string_interactions("WEE1")

    (record,) = result["records"]
    assert result["source"] == "STRING"
    assert record["partner"] == "CDK1"
    assert record["combined_score"] == 0.998
    assert record["experimental_score"] == 0.731
    assert record["textmining_score"] == 0.957


async def test_reactome_resolves_the_entity_before_asking_for_pathways(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    result = await databases.search_reactome_pathways("WEE1")

    (record,) = result["records"]
    assert record["pathway_id"] == "R-HSA-69478"
    assert record["name"] == "G2/M DNA replication"
    assert "R-HSA-69253" in client.calls[1][0]


async def test_reactome_without_a_matching_entity_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = stub_responses(monkeypatch, {"results": []})

    result = await databases.search_reactome_pathways("NOTAGENE")

    assert result["records"] == []
    assert len(client.calls) == 1


async def test_open_targets_reports_only_satisfied_tractability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """False tractability buckets dominate the response and are rebilled on
    every tool turn."""
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

    result = await databases.search_open_targets("WEE1")

    (record,) = result["records"]
    assert record["symbol"] == "WEE1"
    assert record["associated_diseases"] == [
        {"disease": "glioma", "score": 0.51}
    ]
    assert record["tractability"] == ["SM: Clinical Precedence"]


@pytest.mark.parametrize(
    ("tool", "source"),
    [
        (databases.search_clinical_trials, "ClinicalTrials.gov"),
        (databases.search_ensembl_gene, "Ensembl"),
        (databases.search_gnomad_constraint, "gnomAD"),
        (databases.search_string_interactions, "STRING"),
        (databases.search_reactome_pathways, "Reactome"),
        (databases.search_open_targets, "Open Targets"),
    ],
)
async def test_a_failed_request_degrades_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch, tool: Any, source: str
) -> None:
    stub_failure(monkeypatch, httpx.ConnectError("boom"))

    assert await tool("WEE1") == {
        "source": source,
        "query": "WEE1",
        "records": [],
    }


_RS_ID = "rs334"
_ASSOCIATION_URL = (
    "https://www.ebi.ac.uk/gwas/rest/api/v2/associations/226290633"
)


def _payload() -> dict[str, Any]:
    return {
        "page": {
            "size": 1,
            "totalElements": 134,
            "totalPages": 134,
            "number": 0,
        },
        "_embedded": {
            "associations": [
                {
                    "association_id": 226290633,
                    "accession_id": "GCST90480652",
                    "p_value": 3e-31,
                    "beta": "0.1401 unit increase",
                    "risk_frequency": "0.9614",
                    "ci_lower": 0.12,
                    "ci_upper": 0.16,
                    "efo_traits": [
                        {"efo_id": "EFO_0004309", "efo_trait": "platelet count"}
                    ],
                    "reported_trait": [
                        "platelet count (minimum, inv-norm transformed)"
                    ],
                    "mapped_genes": ["HBB"],
                    "pubmed_id": "39024449",
                    "snp_effect_allele": ["rs334-T"],
                    "_links": {"self": {"href": _ASSOCIATION_URL}},
                }
            ]
        },
    }


async def test_association_lookup_preserves_source_and_effect_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = transport_responses(monkeypatch, _payload())

    result = await databases.search_gwas_catalog_associations(_RS_ID)

    (record,) = result["records"]
    assert result["source"] == "GWAS Catalog"
    assert result["query"] == {"rs_id": _RS_ID, "page": 0, "size": 20}
    assert result["access_date"]
    assert record["association_id"] == 226290633
    assert record["study_accession"] == "GCST90480652"
    assert record["trait"] == "platelet count"
    assert record["p_value"] == 3e-31
    assert record["confidence_interval"] == [0.12, 0.16]
    assert record["mapped_genes"] == ["HBB"]
    assert record["source_url"] == _ASSOCIATION_URL
    assert "does not establish causality" in record["interpretation"]
    assert result["page"]["total_elements"] == 134
    assert dict(requests[0].url.params) == {
        "rs_id": _RS_ID,
        "page": "0",
        "size": "20",
    }


async def test_invalid_rs_id_is_rejected_without_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = transport_responses(monkeypatch)

    result = await databases.search_gwas_catalog_associations("rs334 OR 1=1")

    assert result["records"] == []
    assert result["error"] == "rs_id must be an rs identifier such as rs334"
    assert requests == []


async def test_lookup_clamps_page_and_size_to_the_bounded_api_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = transport_responses(monkeypatch, _payload())

    await databases.search_gwas_catalog_associations(
        _RS_ID, size=10_000, page=10_000
    )

    assert dict(requests[0].url.params) == {
        "rs_id": _RS_ID,
        "page": str(databases.MAX_PAGE),
        "size": str(databases.MAX_PAGE_SIZE),
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"page": {}, "_embedded": {"associations": []}},
        {"page": {"totalElements": 0}, "_links": {"self": {"href": "x"}}},
    ],
)
async def test_a_valid_empty_lookup_is_not_an_error(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> None:
    transport_responses(monkeypatch, payload)

    result = await databases.search_gwas_catalog_associations(_RS_ID)

    assert result["records"] == []
    assert "error" not in result


def _without_accession() -> dict[str, Any]:
    payload = _payload()
    del payload["_embedded"]["associations"][0]["accession_id"]
    return payload


@pytest.mark.parametrize(
    ("response", "expected_error"),
    [
        (httpx.ConnectError("offline"), "ConnectError"),
        (httpx.ReadTimeout("slow"), "ReadTimeout"),
        (httpx.Response(429, json={"message": "secret"}), "429"),
        (httpx.Response(500, json={"message": "secret"}), "500"),
        (_without_accession(), "study accession"),
        *(
            (
                {
                    "page": {"totalElements": total},
                    "_links": {"self": {"href": "x"}},
                },
                "association list",
            )
            for total in (1, "0", None)
        ),
    ],
)
async def test_failures_are_errors_never_a_lookup_with_no_associations(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    response: Any,
    expected_error: str,
) -> None:
    caplog.set_level(logging.WARNING, logger=databases.__name__)
    transport_responses(monkeypatch, response)

    result = await databases.search_gwas_catalog_associations(_RS_ID)

    assert result["records"] == []
    assert expected_error in result["error"]
    assert "secret" not in repr(result) + caplog.text


async def test_catalog_lookup_is_callable_under_the_campaign_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport_responses(monkeypatch, _payload())
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")

    async with registered_tools() as client:
        result = await client.call_tool(
            "search_gwas_catalog_associations", {"rs_id": _RS_ID, "size": 1}
        )

    assert result.data["records"][0]["study_accession"] == "GCST90480652"
