"""Tests for the INDRA CoGex client and all eight tools' error contracts."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx
import pytest
from mcp_server.tests._httpx import stub_failure, stub_responses
from mcp_server.tools.indra_cogex.associations import (
    query_gene_codependents,
    query_gene_disease_network,
)
from mcp_server.tools.indra_cogex.client import (
    INDRA_BASE_URL,
    cap_results,
    indra_post,
    maybe_parse_agent,
    parse_id,
    tool_error,
)
from mcp_server.tools.indra_cogex.drug_clinical import (
    query_clinical_trials,
    query_drug_info,
)
from mcp_server.tools.indra_cogex.enrichment import run_enrichment_analysis
from mcp_server.tools.indra_cogex.pathways import (
    query_causal_subnetwork,
    query_pathways,
)
from mcp_server.tools.indra_cogex.statements import (
    query_mechanistic_statements,
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
