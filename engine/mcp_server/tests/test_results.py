import json
from typing import Any

import httpx
import pytest
from mcp_server.tests._entrez import install_entrez
from mcp_server.tests._httpx import registered_tools, transport_responses
from mcp_server.tools import web_providers
from mcp_server.tools.lit_review import search_pubmed
from mcp_server.tools.web_fetch import UrlNotFetchableError, read_url

_RECORD_TOOLS = [
    ("search_chembl", {"query": "aspirin"}, "ChEMBL"),
    ("search_uniprot", {"query": "EGFR"}, "UniProtKB/Swiss-Prot"),
    ("search_clinical_trials", {"query": "imatinib"}, "ClinicalTrials.gov"),
    ("search_ensembl_gene", {"query": "WEE1"}, "Ensembl"),
    ("search_gnomad_constraint", {"query": "WEE1"}, "gnomAD"),
    ("search_string_interactions", {"query": "WEE1"}, "STRING"),
    ("search_reactome_pathways", {"query": "WEE1"}, "Reactome"),
    ("search_open_targets", {"query": "WEE1"}, "Open Targets"),
    ("search_europepmc", {"query": "WEE1"}, "Europe PMC"),
    ("search_preprints", {"query": "WEE1"}, "Preprints"),
    ("search_biorxiv", {"query": "WEE1"}, "bioRxiv"),
    ("search_arxiv", {"query": "WEE1"}, "arXiv"),
]


def _assert_error(error: Any, kind: str) -> None:
    assert isinstance(error, dict)
    assert error["kind"] == kind
    assert isinstance(error["detail"], str) and error["detail"]


@pytest.mark.parametrize(("tool_name", "arguments", "source"), _RECORD_TOOLS)
async def test_an_upstream_refusal_is_an_explicit_failed_result_not_a_raise_or_no_match(
    monkeypatch: pytest.MonkeyPatch, tool_name: str, arguments: dict[str, Any], source: str
) -> None:
    transport_responses(monkeypatch, *[httpx.Response(503, json={})] * 3)

    async with registered_tools() as client:
        result = await client.call_tool(tool_name, arguments, raise_on_error=False)

    assert result.is_error is not True
    assert result.data["source"] == source
    assert result.data["records"] == []
    _assert_error(result.data["error"], "http_status")
    assert result.data["error"]["status_code"] == 503


@pytest.mark.parametrize(("tool_name", "arguments", "source"), _RECORD_TOOLS)
async def test_an_unreachable_upstream_is_an_explicit_failed_result(
    monkeypatch: pytest.MonkeyPatch, tool_name: str, arguments: dict[str, Any], source: str
) -> None:
    transport_responses(monkeypatch, *[httpx.ConnectError("connection refused")] * 3)

    async with registered_tools() as client:
        result = await client.call_tool(tool_name, arguments, raise_on_error=False)

    assert result.is_error is not True
    assert result.data["records"] == []
    _assert_error(result.data["error"], "network_error")


async def test_an_unknown_gene_symbol_is_an_empty_answer_not_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport_responses(monkeypatch, httpx.Response(404, json={"error": "No valid lookup"}))

    async with registered_tools() as client:
        result = await client.call_tool("search_ensembl_gene", {"query": "NOTAGENE"})

    assert result.data == {"source": "Ensembl", "query": "NOTAGENE", "records": []}


async def test_openalex_failure_is_an_explicit_failed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport_responses(monkeypatch, *[httpx.Response(503, json={})] * 3)

    async with registered_tools() as client:
        result = await client.call_tool("search_openalex", {"query": "WEE1"}, raise_on_error=False)

    assert result.is_error is not True
    _assert_error(result.data["error"], "http_status")
    assert set(result.data) == {"error"}


async def test_citation_edge_failures_are_explicit_failed_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport_responses(monkeypatch, httpx.Response(503, json={}))

    async with registered_tools() as client:
        outage = await client.call_tool(
            "get_opencitations_citation_edges", {"doi": "10.1234/example"}, raise_on_error=False
        )
        invalid = await client.call_tool(
            "get_opencitations_citation_edges", {"doi": "not a doi"}, raise_on_error=False
        )

    assert outage.is_error is not True
    assert outage.data["doi"] == "10.1234/example"
    _assert_error(outage.data["error"], "http_status")
    assert invalid.is_error is not True
    _assert_error(invalid.data["error"], "invalid_request")


async def test_pubmed_failures_are_explicit_failed_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    def refuse(**_kwargs: Any) -> Any:
        raise RuntimeError("Search Backend failed")

    install_entrez(monkeypatch, esearch=refuse)
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(tmp_path))

    searched = json.loads(search_pubmed.search_pubmed("WEE1"))
    fulltext = await search_pubmed.pubmed_search_with_fulltext("WEE1", slug="goal")
    invalid = await search_pubmed.pubmed_search_with_fulltext("WEE1", slug="../escape")

    assert searched["results"] == [] and searched["count"] == 0
    _assert_error(searched["error"], "unavailable")
    _assert_error(fulltext["error"], "unavailable")
    _assert_error(invalid["error"], "invalid_request")


async def test_a_web_search_outage_is_an_explicit_failed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BRAVE_API_KEY", "k")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    transport_responses(monkeypatch, httpx.Response(429, json={}))

    result = await web_providers.search_web("WEE1")

    _assert_error(result["error"], "http_status")
    assert result["error"]["status_code"] == 429


@pytest.mark.parametrize(
    ("url", "response", "kind"),
    [
        ("http://127.0.0.1/admin", None, "blocked"),
        ("https://example.com/missing", httpx.Response(404), "http_status"),
        ("https://example.com/down", httpx.ConnectError("refused"), "network_error"),
    ],
)
async def test_an_unreadable_url_is_an_explicit_failed_result(
    monkeypatch: pytest.MonkeyPatch, url: str, response: Any, kind: str
) -> None:
    monkeypatch.setattr(
        "mcp_server.tools.web_fetch.check_fetchable",
        lambda target: None if "example.com" in target else _refuse(target),
    )
    if response is not None:
        transport_responses(monkeypatch, response)

    result = json.loads(await read_url(url))

    assert result["url"] == url
    _assert_error(result["error"], kind)


def _refuse(target: str) -> None:
    raise UrlNotFetchableError(f"host not allowed: {target}")


@pytest.mark.parametrize(
    ("result", "described"),
    [
        (
            {"source": "S", "query": "q", "records": [], "error": {"kind": "timeout"}},
            "failed (timeout)",
        ),
        ({"source": "S", "query": "q", "records": []}, "empty"),
        ({"source": "S", "query": "q", "records": [{}, {}]}, "2 items"),
    ],
)
def test_call_logs_tell_a_failed_lookup_from_an_empty_one(result: Any, described: str) -> None:
    from mcp_server.tool_logging import _describe_result

    assert _describe_result(result) == described
