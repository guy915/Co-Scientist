"""Offline contracts for indra cogex."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx
import pytest
from mcp_server.tests._httpx import (
    stub_failure,
    stub_responses,
    stub_unreachable,
)
from mcp_server.tools.indra_cogex import (
    INDRA_BASE_URL,
    cap_results,
    indra_post,
    maybe_parse_agent,
    parse_id,
    query_causal_subnetwork,
    query_clinical_trials,
    query_drug_info,
    query_gene_codependents,
    query_gene_disease_network,
    query_mechanistic_statements,
    query_pathways,
    run_enrichment_analysis,
    tool_error,
)

# --- parse_id / maybe_parse_agent -------------------------------------


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("HGNC:6407", ["HGNC", "6407"]),
        ("MESH:D002289", ["MESH", "D002289"]),
        # A second colon belongs to the id portion, not a new field.
        ("CHEBI:CHEBI:27690", ["CHEBI", "CHEBI:27690"]),
    ],
)
def test_parse_id_splits_on_first_colon(
    identifier: str, expected: list[str]
) -> None:
    assert parse_id(identifier) == expected


@pytest.mark.parametrize(
    "identifier", ["no-colon-here", ":missing-namespace", "missing-id:"]
)
def test_parse_id_rejects_malformed_identifiers(identifier: str) -> None:
    with pytest.raises(ValueError, match="invalid identifier"):
        parse_id(identifier)


def test_maybe_parse_agent_parses_a_curie() -> None:
    assert maybe_parse_agent("HGNC:6407") == ["HGNC", "6407"]


def test_maybe_parse_agent_keeps_a_plain_name() -> None:
    assert maybe_parse_agent("KRAS") == "KRAS"


def test_maybe_parse_agent_does_not_parse_urls() -> None:
    url = "http://example.com/a:b"
    assert maybe_parse_agent(url) == url


def test_maybe_parse_agent_falls_back_on_unparseable_curie() -> None:
    # No namespace before the colon, so parse_id would raise; the agent
    # helper is more permissive and returns the original string instead.
    assert maybe_parse_agent(":no-namespace") == ":no-namespace"


# --- tool_error / cap_results -------------------------------------------


def test_tool_error_carries_message_and_query() -> None:
    assert tool_error("boom", {"q": 1}) == {"error": "boom", "query": {"q": 1}}


def test_cap_results_truncates_and_reports_the_original_total() -> None:
    capped, total = cap_results([1, 2, 3, 4], 2)
    assert capped == [1, 2]
    assert total == 4


def test_cap_results_passes_non_lists_through_unchanged() -> None:
    # Some CoGex endpoints return an error dict instead of a list; capping
    # that would be wrong, so it is returned as-is with a zero total. The
    # declared return type is list[Any], since that's the typical case;
    # cast documents that this call deliberately exercises the fallback.
    passthrough, total = cap_results({"error": "bad"}, 2)
    assert cast(Any, passthrough) == {"error": "bad"}
    assert total == 0


# --- indra_post -----------------------------------------------------------


async def test_indra_post_returns_parsed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = stub_responses(monkeypatch, {"ok": True})

    result = await indra_post("/api/x", {"a": 1})

    assert result == {"ok": True}
    assert client.calls == [(f"{INDRA_BASE_URL}/api/x", {"a": 1})]


async def test_indra_post_does_not_catch_transport_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The tool owns its error envelope; the HTTP client propagates failures.
    stub_failure(monkeypatch, httpx.ConnectError("boom"))

    with pytest.raises(httpx.ConnectError):
        await indra_post("/api/x", {"a": 1})


# --- cross-tool degrade contract ---------------------------------------

# Exercise the error envelope through each public tool entrypoint.
_ALL_TOOLS: dict[
    str, tuple[Callable[..., Awaitable[dict[str, Any]]], dict[str, Any]]
] = {
    "gene_disease_network": (
        query_gene_disease_network,
        {"identifier": "HGNC:6407", "entity_type": "gene"},
    ),
    "gene_codependents": (
        query_gene_codependents,
        {"gene_id": "HGNC:6407"},
    ),
    "drug_info": (
        query_drug_info,
        {"identifier": "CHEBI:CHEBI:27690", "query_type": "targets"},
    ),
    "clinical_trials": (
        query_clinical_trials,
        {"identifier": "MESH:D000544", "entity_type": "disease"},
    ),
    "pathways": (query_pathways, {"gene_ids": ["HGNC:6407"]}),
    "causal_subnetwork": (
        query_causal_subnetwork,
        {"node_ids": ["HGNC:6407", "HGNC:5173"]},
    ),
    "mechanistic_statements": (
        query_mechanistic_statements,
        {"agent": "KRAS"},
    ),
    "enrichment": (
        run_enrichment_analysis,
        {"gene_list": ["HGNC:6407"], "analysis_type": "discrete"},
    ),
}


@pytest.mark.parametrize(
    "tool_fn,kwargs", _ALL_TOOLS.values(), ids=list(_ALL_TOOLS)
)
async def test_every_tool_degrades_on_transport_failure(
    tool_fn: Callable[..., Awaitable[dict[str, Any]]],
    kwargs: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    stub_failure(monkeypatch, httpx.ConnectError("connection refused"))

    with caplog.at_level(logging.ERROR):
        result = await tool_fn(**kwargs)

    assert set(result) == {"error", "query"}
    assert "connection refused" in result["error"]
    assert isinstance(result["query"], dict)
    assert f"{tool_fn.__name__} failed: connection refused" in caplog.text


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


# --- query_drug_info: all four query_type branches share one dispatch ---
# table (_DRUG_ENDPOINTS in the source), so they are parametrized here too.
# The expected mapping is written out by hand rather than imported from
# that table, so a change to the table itself still has something to check
# it against.


@pytest.mark.parametrize(
    "query_type,endpoint,param_name,result_key",
    [
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
    ],
)
async def test_drug_info_success(
    query_type: str,
    endpoint: str,
    param_name: str,
    result_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = stub_responses(monkeypatch, [{"id": "X"}])

    result = await query_drug_info("CHEBI:CHEBI:27690", query_type=query_type)

    assert result[result_key] == [{"id": "X"}]
    assert result[f"total_{result_key}"] == 1
    call_url, call_payload = client.calls[0]
    assert call_url.endswith(endpoint)
    assert param_name in call_payload


async def test_drug_info_rejects_invalid_query_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_unreachable(monkeypatch)

    result = await query_drug_info("CHEBI:CHEBI:27690", query_type="bogus")

    assert result == {
        "error": (
            "invalid query_type 'bogus', use: targets, drugs_for_target, "
            "indications, side_effects"
        ),
        "query": {
            "identifier": "CHEBI:CHEBI:27690",
            "query_type": "bogus",
        },
    }


# --- query_clinical_trials: disease vs drug -------------------------------


@pytest.mark.parametrize(
    "entity_type,endpoint,param_name",
    [
        ("disease", "/api/get_trials_for_disease", "disease"),
        ("drug", "/api/get_trials_for_drug", "drug"),
    ],
)
async def test_clinical_trials_success(
    entity_type: str,
    endpoint: str,
    param_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = stub_responses(monkeypatch, [{"nct_id": "NCT1"}])

    result = await query_clinical_trials(
        "MESH:D000544", entity_type=entity_type
    )

    assert result["trials"] == [{"nct_id": "NCT1"}]
    assert result["total_trials"] == 1
    call_url, call_payload = client.calls[0]
    assert call_url.endswith(endpoint)
    assert param_name in call_payload


async def test_clinical_trials_rejects_invalid_entity_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_unreachable(monkeypatch)

    result = await query_clinical_trials("MESH:D000544", entity_type="bogus")

    assert result == {
        "error": "invalid entity_type 'bogus', use 'disease' or 'drug'",
        "query": {"identifier": "MESH:D000544", "entity_type": "bogus"},
    }


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
    client = stub_responses(monkeypatch, [{"pathway": "WP1"}])

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
    stub_unreachable(monkeypatch)

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
    client = stub_responses(monkeypatch, [{"stmt": "Activation"}])

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
    stub_unreachable(monkeypatch)

    result = await query_causal_subnetwork(["HGNC:6407", "bad-node"])

    assert result["query"] == {"node_ids": ["HGNC:6407", "bad-node"]}
    assert "invalid identifier" in result["error"]


async def test_statements_by_mesh_term_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = stub_responses(monkeypatch, [{"stmt": "Activation"}])

    result = await query_mechanistic_statements(mesh_term="MESH:D002289")

    assert result["statements"] == [{"stmt": "Activation"}]
    assert result["total_statements"] == 1
    assert result["query"] == {
        "agent": None,
        "other_agent": None,
        "mesh_term": "MESH:D002289",
        "relation_types": None,
    }
    call_url, call_payload = client.calls[0]
    assert call_url.endswith("/api/get_stmts_for_mesh")
    assert call_payload["mesh_term"] == ["MESH", "D002289"]
    assert call_payload["include_child_terms"] is True


async def test_statements_by_agent_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = stub_responses(monkeypatch, [{"stmt": "Inhibition"}])

    result = await query_mechanistic_statements(agent="KRAS")

    assert result["statements"] == [{"stmt": "Inhibition"}]
    call_url, call_payload = client.calls[0]
    assert call_url.endswith("/api/get_statements")
    # A plain name is sent as-is rather than parsed into a CURIE.
    assert call_payload["agent"] == "KRAS"
    assert "other_agent" not in call_payload
    assert "rel_types" not in call_payload
    assert "agent_role" not in call_payload


async def test_statements_by_agent_includes_only_given_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = stub_responses(monkeypatch, [])

    await query_mechanistic_statements(
        agent="HGNC:6407",
        other_agent="HGNC:1097",
        relation_types=["Activation"],
        agent_role="subject",
    )

    _, call_payload = client.calls[0]
    assert call_payload["agent"] == ["HGNC", "6407"]
    assert call_payload["other_agent"] == ["HGNC", "1097"]
    assert call_payload["rel_types"] == ["Activation"]
    assert call_payload["agent_role"] == "subject"


async def test_statements_requires_agent_or_mesh_term(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_unreachable(monkeypatch)

    result = await query_mechanistic_statements()

    assert result == {
        "error": "provide either 'agent' or 'mesh_term'",
        "query": {
            "agent": None,
            "other_agent": None,
            "mesh_term": None,
            "relation_types": None,
        },
    }


async def test_statements_reports_a_malformed_mesh_term(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_unreachable(monkeypatch)

    result = await query_mechanistic_statements(mesh_term="no-colon")

    assert result["query"]["mesh_term"] == "no-colon"
    assert "invalid identifier" in result["error"]
