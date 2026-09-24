"""Tests for normalized ChEMBL and UniProt MCP retrieval tools."""

import logging
from typing import Any

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from httpx import ASGITransport, AsyncClient
from mcp_server.tests._httpx import stub_failure, stub_responses
from mcp_server.tools import biomedical_databases
from starlette.applications import Starlette

_REAL_ASYNC_CLIENT = httpx.AsyncClient
_MOCK_TRANSPORT = httpx.MockTransport


class _ErrorStatusClient:
    """A canned httpx.AsyncClient returning a real non-2xx response.

    Uses a genuine ``httpx.Response`` (rather than the shared
    ``StubResponse``, whose ``raise_for_status`` never raises) so this
    path raises the real ``httpx.HTTPStatusError`` a 503 from EBI during
    an outage would produce. That is what keeps it a local class rather
    than another caller of ``stub_responses``.
    """

    def __init__(self, status_code: int) -> None:
        self._status_code = status_code

    async def __aenter__(self) -> "_ErrorStatusClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def get(self, *_: Any, **__: Any) -> httpx.Response:
        return httpx.Response(
            self._status_code,
            request=httpx.Request("GET", "https://example.test"),
        )


def _mcp_client_factory(app: Any):  # type: ignore[no-untyped-def]
    def factory(**kwargs: Any) -> AsyncClient:
        kwargs.pop("follow_redirects", None)
        return _REAL_ASYNC_CLIENT(
            **kwargs,
            transport=ASGITransport(app=app),
            base_url="http://test",
        )

    return factory


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
    """The public MCP contract preserves results and marks provider errors."""
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
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: _REAL_ASYNC_CLIENT(
            transport=_MOCK_TRANSPORT(handler), **kwargs
        ),
    )
    mcp_app = mcp.http_app()
    app = Starlette(lifespan=mcp_app.lifespan)
    app.mount("/", mcp_app)
    transport = StreamableHttpTransport(
        "http://test/mcp", httpx_client_factory=_mcp_client_factory(app)
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
    # A transient outage keeps provider failure local to this source.
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
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **_: _ErrorStatusClient(503)
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
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **_: _ErrorStatusClient(503)
    )
    result = await biomedical_databases.search_uniprot("EGFR")
    assert result == {
        "source": "UniProtKB/Swiss-Prot",
        "query": "EGFR",
        "records": [],
        "error": {"kind": "http_status", "status_code": 503},
    }
