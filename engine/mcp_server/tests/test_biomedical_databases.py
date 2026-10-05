import logging
from typing import Any

import httpx
import mcp_server.tools.biomedical_databases as clinical_trials
import mcp_server.tools.biomedical_databases as genomics_databases
import mcp_server.tools.biomedical_databases as gwas_catalog
import mcp_server.tools.biomedical_databases as systems_biology
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from mcp_server.campaign import PUBLIC_TOOLS
from mcp_server.server import _MCP_TOOLS, mcp
from mcp_server.tests._httpx import (
    asgi_client_factory,
    stub_failure,
    stub_responses,
    transport_responses,
)
from mcp_server.tools import biomedical_databases
from starlette.applications import Starlette


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
            "record_key": "chembl_id",
            "record_value": "CHEMBL25",
        },
        {
            "tool_name": "search_uniprot",
            "query": "EGFR",
            "source": "UniProtKB/Swiss-Prot",
            "success_payload": {"results": [{"primaryAccession": "P00533"}]},
            "record_key": "accession",
            "record_value": "P00533",
        },
    ],
)
async def test_registered_biomedical_tools_report_outcome_at_mcp_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tool_case: dict[str, Any],
) -> None:
    from mcp_server.server import mcp

    tool_name = tool_case["tool_name"]
    query = tool_case["query"]
    source = tool_case["source"]
    success_payload = tool_case["success_payload"]
    record_key = tool_case["record_key"]
    record_value = tool_case["record_value"]
    responses: list[httpx.Response | Exception] = [
        httpx.Response(200, json=success_payload),
        httpx.Response(
            200,
            json={"molecules": [], "results": []},
        ),
        httpx.Response(503, json={}),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={}),
        httpx.ReadTimeout("upstream timeout"),
    ]
    requests = transport_responses(monkeypatch, *responses)
    mcp_app = mcp.http_app()
    app = Starlette(lifespan=mcp_app.lifespan)
    app.mount("/", mcp_app)
    transport = StreamableHttpTransport(
        "http://test/mcp", httpx_client_factory=asgi_client_factory(app)
    )

    async with app.router.lifespan_context(app), Client(transport) as client:
        tool_names = {tool.name for tool in await client.list_tools()}
        results = [
            await client.call_tool(tool_name, {"query": query})
            for _ in range(6)
        ]

    assert tool_name in tool_names
    success, empty, http_error, parse_error, shape_error, timeout = results
    assert success.is_error is not True
    assert success.data["source"] == source
    assert success.data["query"] == query
    assert success.data["records"][0][record_key] == record_value
    assert "error" not in success.data
    assert empty.is_error is not True
    assert empty.data == {
        "source": source,
        "query": query,
        "records": [],
    }
    assert http_error.data == {
        "source": source,
        "query": query,
        "records": [],
        "error": {"kind": "http_status", "status_code": 503},
    }
    assert parse_error.data == {
        "source": source,
        "query": query,
        "records": [],
        "error": {"kind": "invalid_response"},
    }
    assert shape_error.data == {
        "source": source,
        "query": query,
        "records": [],
        "error": {"kind": "invalid_response"},
    }
    assert timeout.data == {
        "source": source,
        "query": query,
        "records": [],
        "error": {"kind": "timeout"},
    }
    assert all(result.is_error is not True for result in results)
    assert len(requests) == 6


async def test_search_chembl_normalizes_molecule_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_responses(
        monkeypatch,
        {
            "molecules": [
                {
                    "molecule_chembl_id": "CHEMBL25",
                    "pref_name": "ASPIRIN",
                    "molecule_type": "Small molecule",
                    "max_phase": 4,
                    "first_approval": 1950,
                }
            ]
        },
    )
    result = await biomedical_databases.search_chembl("aspirin")
    assert result["source"] == "ChEMBL"
    assert result["records"][0]["chembl_id"] == "CHEMBL25"


async def test_search_uniprot_returns_reviewed_functional_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_responses(
        monkeypatch,
        {
            "results": [
                {
                    "primaryAccession": "P00533",
                    "genes": [{"geneName": {"value": "EGFR"}}],
                    "proteinDescription": {
                        "recommendedName": {"fullName": {"value": "EGFR"}}
                    },
                    "organism": {"scientificName": "Homo sapiens"},
                    "comments": [
                        {
                            "commentType": "FUNCTION",
                            "texts": [{"value": "Kinase."}],
                        }
                    ],
                }
            ]
        },
    )
    result = await biomedical_databases.search_uniprot("EGFR")
    assert result["source"] == "UniProtKB/Swiss-Prot"
    assert result["records"][0]["gene"] == "EGFR"
    assert result["records"][0]["functions"] == ["Kinase."]


async def test_search_chembl_degrades_on_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    stub_failure(monkeypatch, httpx.ConnectError("connection refused"))
    with caplog.at_level(logging.WARNING):
        result = await biomedical_databases.search_chembl("aspirin")
    assert result == {
        "source": "ChEMBL",
        "query": "aspirin",
        "records": [],
        "error": {"kind": "network_error"},
    }
    assert "ChEMBL search failed for 'aspirin'" in caplog.text


async def test_search_uniprot_degrades_on_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    stub_failure(monkeypatch, httpx.ConnectError("connection refused"))
    with caplog.at_level(logging.WARNING):
        result = await biomedical_databases.search_uniprot("EGFR")
    assert result == {
        "source": "UniProtKB/Swiss-Prot",
        "query": "EGFR",
        "records": [],
        "error": {"kind": "network_error"},
    }
    assert "UniProt search failed for 'EGFR'" in caplog.text


async def test_search_chembl_degrades_on_http_status_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_responses(
        monkeypatch,
        httpx.Response(
            503, request=httpx.Request("GET", "https://example.test")
        ),
    )
    result = await biomedical_databases.search_chembl("aspirin")
    assert result == {
        "source": "ChEMBL",
        "query": "aspirin",
        "records": [],
        "error": {"kind": "http_status", "status_code": 503},
    }


async def test_search_uniprot_degrades_on_http_status_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_responses(
        monkeypatch,
        httpx.Response(
            503, request=httpx.Request("GET", "https://example.test")
        ),
    )
    result = await biomedical_databases.search_uniprot("EGFR")
    assert result == {
        "source": "UniProtKB/Swiss-Prot",
        "query": "EGFR",
        "records": [],
        "error": {"kind": "http_status", "status_code": 503},
    }


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

    result = await clinical_trials.search_clinical_trials("adavosertib")

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

    result = await clinical_trials.search_clinical_trials("nothing")

    (record,) = result["records"]
    assert record["status"] is None
    assert record["interventions"] == []


class TestClinicalTrials:
    async def test_a_failed_request_degrades_instead_of_raising(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        stub_failure(monkeypatch, httpx.ConnectError("boom"))

        result = await clinical_trials.search_clinical_trials("adavosertib")

        assert result == {
            "source": "ClinicalTrials.gov",
            "query": "adavosertib",
            "records": [],
        }


async def test_ensembl_carries_the_stable_identifier_and_locus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gene symbols can be renamed or reused; stable ids make claims
    comparable."""
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

    result = await genomics_databases.search_gnomad_constraint("WEE1")

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

    result = await genomics_databases.search_gnomad_constraint("XYZ")

    assert result["records"] == []


class TestGenomicsDatabases:
    @pytest.mark.parametrize(
        ("tool", "source"),
        [
            (genomics_databases.search_ensembl_gene, "Ensembl"),
            (genomics_databases.search_gnomad_constraint, "gnomAD"),
        ],
    )
    async def test_a_failed_request_degrades_instead_of_raising(
        self, monkeypatch: pytest.MonkeyPatch, tool: object, source: str
    ) -> None:
        stub_failure(monkeypatch, httpx.ConnectError("boom"))

        result = await tool("WEE1")  # type: ignore[operator]

        assert result == {"source": source, "query": "WEE1", "records": []}


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
    """Text matches find entities; membership is a separate lookup keyed by
    resolved entity id."""
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
    assert "R-HSA-69253" in client.calls[1][0]


async def test_reactome_without_a_matching_entity_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = stub_responses(monkeypatch, {"results": []})

    result = await systems_biology.search_reactome_pathways("NOTAGENE")

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


class TestSystemsBiology:
    @pytest.mark.parametrize(
        ("tool", "source"),
        [
            (systems_biology.search_string_interactions, "STRING"),
            (systems_biology.search_reactome_pathways, "Reactome"),
            (systems_biology.search_open_targets, "Open Targets"),
        ],
    )
    async def test_a_failed_request_degrades_instead_of_raising(
        self, monkeypatch: pytest.MonkeyPatch, tool: object, source: str
    ) -> None:
        stub_failure(monkeypatch, httpx.ConnectError("boom"))

        result = await tool("WEE1")  # type: ignore[operator]

        assert result == {"source": source, "query": "WEE1", "records": []}


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
        "_links": {
            "next": {
                "href": (
                    "https://www.ebi.ac.uk/gwas/rest/api/v2/associations"
                    "?rs_id=rs334&page=1&size=1"
                )
            }
        },
    }


async def test_association_lookup_preserves_source_and_effect_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = transport_responses(monkeypatch, _payload())

    result = await gwas_catalog.search_gwas_catalog_associations(_RS_ID)

    (record,) = result["records"]
    assert result["source"] == "GWAS Catalog"
    assert result["query"] == {"rs_id": _RS_ID, "page": 0, "size": 20}
    assert result["access_date"]
    assert result["source_url"].startswith(
        "https://www.ebi.ac.uk/gwas/rest/api/v2/associations?"
    )
    assert record["association_id"] == 226290633
    assert record["study_accession"] == "GCST90480652"
    assert record["trait"] == "platelet count"
    assert record["p_value"] == 3e-31
    assert record["beta"] == "0.1401 unit increase"
    assert record["confidence_interval"] == [0.12, 0.16]
    assert record["mapped_genes"] == ["HBB"]
    assert record["pubmed_id"] == "39024449"
    assert record["source_url"] == _ASSOCIATION_URL
    assert "does not establish causality" in record["interpretation"]
    assert result["page"]["total_elements"] == 134
    assert len(requests) == 1
    assert dict(requests[0].url.params) == {
        "rs_id": _RS_ID,
        "page": "0",
        "size": "20",
    }


async def test_invalid_rs_id_is_rejected_without_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = transport_responses(monkeypatch)

    result = await gwas_catalog.search_gwas_catalog_associations("rs334 OR 1=1")

    assert result["records"] == []
    assert result["error"] == "rs_id must be an rs identifier such as rs334"
    assert requests == []


async def test_lookup_clamps_page_and_size_to_the_bounded_api_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = transport_responses(monkeypatch, _payload())

    result = await gwas_catalog.search_gwas_catalog_associations(
        _RS_ID, size=10_000, page=10_000
    )

    assert result["query"]["size"] == gwas_catalog.MAX_PAGE_SIZE
    assert result["query"]["page"] == gwas_catalog.MAX_PAGE
    assert dict(requests[0].url.params) == {
        "rs_id": _RS_ID,
        "page": str(gwas_catalog.MAX_PAGE),
        "size": str(gwas_catalog.MAX_PAGE_SIZE),
    }


async def test_http_failure_is_distinct_from_a_valid_empty_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = transport_responses(
        monkeypatch,
        httpx.ConnectError("offline"),
        {"page": {}, "_embedded": {"associations": []}},
    )

    failed = await gwas_catalog.search_gwas_catalog_associations(_RS_ID)
    empty = await gwas_catalog.search_gwas_catalog_associations(_RS_ID)

    assert failed["records"] == []
    assert "error" in failed
    assert "error" not in empty
    assert empty["records"] == []
    assert len(requests) == 2


async def test_zero_total_without_embedded_associations_is_valid_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = transport_responses(
        monkeypatch,
        {
            "page": {
                "size": 1,
                "totalElements": 0,
                "totalPages": 0,
                "number": 0,
            },
            "_links": {
                "self": {
                    "href": (
                        "https://www.ebi.ac.uk/gwas/rest/api/v2/associations"
                        "?rs_id=rs9999999999999&page=0&size=1"
                    )
                }
            },
        },
    )

    result = await gwas_catalog.search_gwas_catalog_associations(
        "rs9999999999999", size=1
    )

    assert result["records"] == []
    assert "error" not in result
    assert result["page"]["total_elements"] == 0
    assert len(requests) == 1


@pytest.mark.parametrize("total_elements", [1, "0", None])
async def test_missing_embedded_list_without_integer_zero_total_is_malformed(
    monkeypatch: pytest.MonkeyPatch,
    total_elements: Any,
) -> None:
    transport_responses(
        monkeypatch,
        {
            "page": {"totalElements": total_elements},
            "_links": {"self": {"href": "x"}},
        },
    )

    result = await gwas_catalog.search_gwas_catalog_associations(_RS_ID)

    assert result["records"] == []
    assert "association list" in result["error"]


@pytest.mark.parametrize("status_code", [429, 500])
async def test_http_error_body_and_secret_are_not_returned_or_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    status_code: int,
) -> None:
    secret = "synthetic-user-secret-should-not-escape"
    caplog.set_level(logging.WARNING, logger=gwas_catalog.__name__)
    transport_responses(
        monkeypatch,
        httpx.Response(status_code, json={"message": secret}),
    )

    result = await gwas_catalog.search_gwas_catalog_associations(_RS_ID)

    assert "HTTPStatusError" in result["error"]
    assert str(status_code) in result["error"]
    assert secret not in repr(result)
    assert secret not in caplog.text


async def test_timeout_is_reported_instead_of_looking_like_no_associations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = transport_responses(monkeypatch, httpx.ReadTimeout("slow"))

    result = await gwas_catalog.search_gwas_catalog_associations(_RS_ID)

    assert result["records"] == []
    assert "ReadTimeout" in result["error"]
    assert len(requests) == 1


async def test_record_without_a_study_accession_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload()
    del payload["_embedded"]["associations"][0]["accession_id"]
    transport_responses(monkeypatch, payload)

    result = await gwas_catalog.search_gwas_catalog_associations(_RS_ID)

    assert result["records"] == []
    assert "study accession" in result["error"]


async def test_catalog_lookup_is_on_the_mcp_campaign_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = transport_responses(monkeypatch, _payload())
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")

    mcp_app = mcp.http_app()
    app = Starlette(lifespan=mcp_app.lifespan)
    app.mount("/", mcp_app)
    transport = StreamableHttpTransport(
        "http://test/mcp", httpx_client_factory=asgi_client_factory(app)
    )

    async with app.router.lifespan_context(app), Client(transport) as client:
        tools = await client.list_tools()
        result = await client.call_tool(
            "search_gwas_catalog_associations", {"rs_id": _RS_ID, "size": 1}
        )

    names = {name for _, name in _MCP_TOOLS}
    assert "search_gwas_catalog_associations" in names
    assert "search_gwas_catalog_associations" in PUBLIC_TOOLS
    assert "search_gwas_catalog_associations" in {tool.name for tool in tools}
    assert result.data["records"][0]["study_accession"] == "GCST90480652"
    assert len(requests) == 1
