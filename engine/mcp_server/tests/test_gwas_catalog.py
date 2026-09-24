"""Tests for the bounded GWAS Catalog rsID lookup."""

import logging
from typing import Any

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from httpx import ASGITransport, AsyncClient
from mcp_server.campaign import PUBLIC_TOOLS
from mcp_server.server import _MCP_TOOLS, mcp
from mcp_server.tools import gwas_catalog
from starlette.applications import Starlette

_REAL_ASYNC_CLIENT = httpx.AsyncClient
_MOCK_TRANSPORT = httpx.MockTransport
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


def _install_responses(
    monkeypatch: pytest.MonkeyPatch, responses: list[Any]
) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, httpx.Response):
            return response
        return httpx.Response(200, json=response)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: _REAL_ASYNC_CLIENT(
            transport=_MOCK_TRANSPORT(handler), **kwargs
        ),
    )
    return requests


async def test_association_lookup_preserves_source_and_effect_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _install_responses(monkeypatch, [_payload()])

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
    requests = _install_responses(monkeypatch, [])

    result = await gwas_catalog.search_gwas_catalog_associations("rs334 OR 1=1")

    assert result["records"] == []
    assert result["error"] == "rs_id must be an rs identifier such as rs334"
    assert requests == []


async def test_lookup_clamps_page_and_size_to_the_bounded_api_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _install_responses(monkeypatch, [_payload()])

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
    requests = _install_responses(
        monkeypatch,
        [
            httpx.ConnectError("offline"),
            {"page": {}, "_embedded": {"associations": []}},
        ],
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
    """The official HAL page omits ``_embedded`` when totalElements is zero."""
    requests = _install_responses(
        monkeypatch,
        [
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
            }
        ],
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
    _install_responses(
        monkeypatch,
        [
            {
                "page": {"totalElements": total_elements},
                "_links": {"self": {"href": "x"}},
            }
        ],
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
    _install_responses(
        monkeypatch,
        [httpx.Response(status_code, json={"message": secret})],
    )

    result = await gwas_catalog.search_gwas_catalog_associations(_RS_ID)

    assert "HTTPStatusError" in result["error"]
    assert str(status_code) in result["error"]
    assert secret not in repr(result)
    assert secret not in caplog.text


async def test_timeout_is_reported_instead_of_looking_like_no_associations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _install_responses(monkeypatch, [httpx.ReadTimeout("slow")])

    result = await gwas_catalog.search_gwas_catalog_associations(_RS_ID)

    assert result["records"] == []
    assert "ReadTimeout" in result["error"]
    assert len(requests) == 1


async def test_record_without_a_study_accession_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload()
    del payload["_embedded"]["associations"][0]["accession_id"]
    _install_responses(monkeypatch, [payload])

    result = await gwas_catalog.search_gwas_catalog_associations(_RS_ID)

    assert result["records"] == []
    assert "study accession" in result["error"]


async def test_catalog_lookup_is_on_the_mcp_campaign_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _install_responses(monkeypatch, [_payload()])
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")

    def factory(app: Any):  # type: ignore[no-untyped-def]
        def client_factory(**kwargs: Any) -> AsyncClient:
            kwargs.pop("follow_redirects", None)
            return AsyncClient(
                **kwargs,
                transport=ASGITransport(app=app),
                base_url="http://test",
            )

        return client_factory

    mcp_app = mcp.http_app()
    app = Starlette(lifespan=mcp_app.lifespan)
    app.mount("/", mcp_app)
    transport = StreamableHttpTransport(
        "http://test/mcp", httpx_client_factory=factory(app)
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
