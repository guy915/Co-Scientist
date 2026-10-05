import logging
from typing import Any

import httpx
import pytest
from mcp_server.tests._httpx import (
    stub_failure,
    stub_responses,
    stub_unreachable,
)
from mcp_server.tools.indra_cogex import (
    query_causal_subnetwork,
    query_clinical_trials,
    query_drug_info,
    query_gene_codependents,
    query_gene_disease_network,
    query_mechanistic_statements,
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
        query_gene_disease_network,
        {"identifier": "HGNC:6407", "entity_type": "gene"},
        "/api/get_diseases_for_gene",
        {"gene": _KRAS},
        {"diseases": _ROWS, "total_diseases": 1},
        id="network gene to diseases",
    ),
    pytest.param(
        query_gene_codependents,
        {"gene_id": "HGNC:6407"},
        "/api/get_codependents_for_gene",
        {"gene": _KRAS},
        {"codependent_genes": _ROWS, "total_codependents": 1},
        id="codependents",
    ),
    *(
        pytest.param(
            query_drug_info,
            {"identifier": "CHEBI:CHEBI:27690", "query_type": query_type},
            endpoint,
            {param: _METFORMIN},
            {key: _ROWS, f"total_{key}": 1},
            id=f"drug {query_type}",
        )
        for query_type, endpoint, param, key in (
            ("targets", "/api/get_targets_for_drug", "drug", "targets"),
            (
                "drugs_for_target",
                "/api/get_drugs_for_target",
                "target",
                "drugs",
            ),
            (
                "indications",
                "/api/get_indications_for_drug",
                "molecule",
                "indications",
            ),
            (
                "side_effects",
                "/api/get_side_effects_for_drug",
                "drug",
                "side_effects",
            ),
        )
    ),
    *(
        pytest.param(
            query_clinical_trials,
            {"identifier": "MESH:D000544", "entity_type": entity_type},
            f"/api/get_trials_for_{entity_type}",
            {entity_type: ["MESH", "D000544"]},
            {"trials": _ROWS, "total_trials": 1},
            id=f"trials for {entity_type}",
        )
        for entity_type in ("disease", "drug")
    ),
    pytest.param(
        run_enrichment_analysis,
        {"gene_list": ["HGNC:1"], "analysis_type": "discrete"},
        "/api/discrete_analysis",
        {"gene_list": ["HGNC:1"]},
        {
            "results": _ROWS,
            "query": {"analysis_type": "discrete", "gene_count": 1},
        },
        id="discrete enrichment",
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
        run_enrichment_analysis,
        {"gene_list": ["MAPK1-Y187"], "analysis_type": "kinase"},
        "/api/kinase_analysis",
        {"phosphosite_list": ["MAPK1-Y187"]},
        {"results": _ROWS},
        id="kinase enrichment",
    ),
    pytest.param(
        query_pathways,
        {"gene_ids": ["HGNC:6407"]},
        "/api/get_pathways_for_gene",
        {"gene": _KRAS},
        {
            "pathways": _ROWS,
            "query": {"gene_ids": ["HGNC:6407"], "mode": "single"},
        },
        id="pathways of one gene",
    ),
    pytest.param(
        query_pathways,
        {"gene_ids": ["HGNC:6407", "HGNC:1097"]},
        "/api/get_shared_pathways_for_genes",
        {"genes": [_KRAS, ["HGNC", "1097"]]},
        {"pathways": _ROWS, "total_pathways": 1},
        id="pathways shared by genes",
    ),
    *(
        pytest.param(
            query_causal_subnetwork,
            {"node_ids": ["HGNC:6407"], "find_mediators": mediators},
            endpoint,
            {"nodes": [_KRAS], flag: True},
            {"subnetwork": _ROWS, "total_relations": 1},
            id=f"causal subnetwork mediators={mediators}",
        )
        for mediators, endpoint, flag in (
            (True, "/api/indra_mediated_subnetwork", "order_by_ev_count"),
            (False, "/api/indra_subnetwork_relations", "include_db_evidence"),
        )
    ),
    pytest.param(
        query_mechanistic_statements,
        {"mesh_term": "MESH:D002289"},
        "/api/get_stmts_for_mesh",
        {"mesh_term": ["MESH", "D002289"], "include_child_terms": True},
        {"statements": _ROWS, "total_statements": 1},
        id="statements by mesh term",
    ),
]


@pytest.mark.parametrize(
    ("tool", "kwargs", "endpoint", "payload", "expected"), _DISPATCH
)
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


async def test_gene_disease_network_adds_variants_and_caps_each_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = stub_responses(
        monkeypatch,
        [{"id": "HGNC:1"}, {"id": "HGNC:2"}],
        [{"rsid": "rs1"}],
    )

    result = await query_gene_disease_network(
        "MESH:D000544",
        entity_type="disease",
        include_variants=True,
        max_results=1,
    )

    assert result["genes"] == [{"id": "HGNC:1"}]
    assert result["total_genes"] == 2
    assert result["variants"] == [{"rsid": "rs1"}]
    assert result["total_variants"] == 1
    assert [url.rsplit("/", 1)[1] for url, _ in client.calls] == [
        "get_genes_for_disease",
        "get_variants_for_disease",
    ]


async def test_an_error_object_from_the_service_is_passed_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_responses(monkeypatch, {"error": "bad"})

    result = await query_gene_codependents("HGNC:6407")

    assert result["codependent_genes"] == {"error": "bad"}
    assert result["total_codependents"] == 0


@pytest.mark.parametrize(
    ("agent", "sent"),
    [
        ("KRAS", "KRAS"),
        ("HGNC:6407", _KRAS),
        ("http://example.com/a:b", "http://example.com/a:b"),
        (":no-namespace", ":no-namespace"),
    ],
)
async def test_statement_agents_are_parsed_only_when_they_are_curies(
    monkeypatch: pytest.MonkeyPatch, agent: str, sent: str | list[str]
) -> None:
    client = stub_responses(monkeypatch, [])

    await query_mechanistic_statements(agent=agent)

    url, payload = client.calls[0]
    assert url.endswith("/api/get_statements")
    assert payload["agent"] == sent
    assert not {"other_agent", "rel_types", "agent_role"} & payload.keys()


async def test_statements_send_the_filters_they_were_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = stub_responses(monkeypatch, [])

    await query_mechanistic_statements(
        agent="HGNC:6407",
        other_agent="HGNC:1097",
        relation_types=["Activation"],
        agent_role="subject",
    )

    _, payload = client.calls[0]
    assert payload["other_agent"] == ["HGNC", "1097"]
    assert payload["rel_types"] == ["Activation"]
    assert payload["agent_role"] == "subject"


@pytest.mark.parametrize(
    ("tool", "kwargs", "message"),
    [
        (
            query_gene_disease_network,
            {"identifier": "HGNC:6407", "entity_type": "bogus"},
            "invalid entity_type 'bogus', use 'disease' or 'gene'",
        ),
        (
            query_drug_info,
            {"identifier": "CHEBI:CHEBI:27690", "query_type": "bogus"},
            "invalid query_type 'bogus', use: targets, drugs_for_target, "
            "indications, side_effects",
        ),
        (
            query_clinical_trials,
            {"identifier": "MESH:D000544", "entity_type": "bogus"},
            "invalid entity_type 'bogus', use 'disease' or 'drug'",
        ),
        (
            run_enrichment_analysis,
            {"gene_list": ["HGNC:1"], "analysis_type": "bogus"},
            "invalid analysis_type 'bogus', use: discrete, signed, kinase",
        ),
        (
            run_enrichment_analysis,
            {"gene_list": ["HGNC:1"], "analysis_type": "signed"},
            "signed analysis requires 'negative_genes'",
        ),
        (
            query_mechanistic_statements,
            {},
            "provide either 'agent' or 'mesh_term'",
        ),
        (
            query_gene_disease_network,
            {"identifier": "not-a-curie", "entity_type": "gene"},
            "invalid identifier",
        ),
        (
            query_pathways,
            {"gene_ids": ["HGNC:6407", "no-colon"]},
            "invalid identifier",
        ),
        (
            query_causal_subnetwork,
            {"node_ids": ["HGNC:6407", "bad-node"]},
            "invalid identifier",
        ),
        (
            query_mechanistic_statements,
            {"mesh_term": "no-colon"},
            "invalid identifier",
        ),
    ],
)
async def test_a_bad_request_is_reported_without_reaching_the_service(
    monkeypatch: pytest.MonkeyPatch,
    tool: Any,
    kwargs: dict[str, Any],
    message: str,
) -> None:
    stub_unreachable(monkeypatch)

    result = await tool(**kwargs)

    assert set(result) == {"error", "query"}
    assert message in result["error"]
