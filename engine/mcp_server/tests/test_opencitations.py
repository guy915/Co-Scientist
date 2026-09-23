"""OpenCitations citation-edge tool tests."""

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from httpx import ASGITransport, AsyncClient
from mcp_server.campaign import PUBLIC_TOOLS
from mcp_server.server import mcp
from mcp_server.tools.lit_review import opencitations
from starlette.applications import Starlette

_REAL_ASYNC_CLIENT = httpx.AsyncClient
_MOCK_TRANSPORT = httpx.MockTransport
_DOI = "10.1108/jd-12-2013-0166"


async def _no_wait_for_slot() -> None:
    """Keep fake-transport tests independent of the process-wide pacer."""


def _client_factory(app: Any):  # type: ignore[no-untyped-def]
    def factory(**kwargs: Any) -> AsyncClient:
        kwargs.pop("follow_redirects", None)
        return AsyncClient(
            **kwargs,
            transport=ASGITransport(app=app),
            base_url="http://test",
        )

    return factory


async def test_citation_edges_is_available_on_the_mcp_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The server advertises the citation lookup over its public MCP path."""
    responses = [
        [{"count": "1"}],
        [{"count": "1"}],
        [
            {
                "oci": "1-2",
                "citing": "omid:br/1 doi:10.1234/citing",
                "cited": f"doi:{_DOI} omid:br/2",
                "creation": "2025-01-01",
            }
        ],
        [
            {
                "oci": "3-4",
                "citing": f"doi:{_DOI} omid:br/3",
                "cited": "doi:10.1234/referenced",
            }
        ],
    ]
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, json=responses.pop(0))

    monkeypatch.setattr(
        opencitations.httpx,
        "AsyncClient",
        lambda **kwargs: _REAL_ASYNC_CLIENT(
            transport=_MOCK_TRANSPORT(handler), **kwargs
        ),
    )
    monkeypatch.setattr(
        opencitations, "_wait_for_request_slot", _no_wait_for_slot
    )
    mcp_app = mcp.http_app()
    app = Starlette(lifespan=mcp_app.lifespan)
    app.mount("/", mcp_app)
    transport = StreamableHttpTransport(
        "http://test/mcp", httpx_client_factory=_client_factory(app)
    )

    async with app.router.lifespan_context(app), Client(transport) as client:
        tools = await client.list_tools()
        result = await client.call_tool(
            "get_opencitations_citation_edges", {"doi": _DOI}
        )
    tool_name = "get_opencitations_citation_edges"
    assert tool_name in {tool.name for tool in tools}
    assert tool_name in PUBLIC_TOOLS
    assert result.data["citations"]["edges"][0]["cited"] == [
        f"doi:{_DOI}",
        "omid:br/2",
    ]
    assert result.data["references"]["edges"][0]["citing"] == [
        f"doi:{_DOI}",
        "omid:br/3",
    ]
    assert result.data["source"] == "OpenCitations Index v2"
    assert result.data["citations"]["edge_request_url"] == requests[2]
    assert result.data["references"]["edge_request_url"] == requests[3]
    assert "do not establish" in result.data["interpretation_note"]
    assert len(requests) == 4


def _install_responses(
    monkeypatch: pytest.MonkeyPatch, responses: list[Any]
) -> list[str]:
    """Route the tool's HTTP requests through a queued MockTransport."""
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, httpx.Response):
            return response
        return httpx.Response(200, json=response)

    monkeypatch.setattr(
        opencitations.httpx,
        "AsyncClient",
        lambda **kwargs: _REAL_ASYNC_CLIENT(
            transport=_MOCK_TRANSPORT(handler), **kwargs
        ),
    )
    monkeypatch.setattr(
        opencitations, "_wait_for_request_slot", _no_wait_for_slot
    )
    return requests


async def test_zero_counts_are_reported_without_fetching_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _install_responses(
        monkeypatch, [[{"count": "0"}], [{"count": "0"}]]
    )

    result = await opencitations.get_opencitations_citation_edges(_DOI)

    assert len(requests) == 2
    assert result["citation_count"] == result["reference_count"] == 0
    assert result["citations"]["edge_fetch_status"] == "zero_indexed"
    assert result["references"]["edge_fetch_status"] == "zero_indexed"
    assert result["citations"]["count_request_url"] == requests[0]
    assert result["references"]["count_request_url"] == requests[1]


@pytest.mark.parametrize(
    "doi",
    [
        "https://example.com/not-a-doi",
        "10.1234/" + ("x" * 257),
    ],
)
async def test_invalid_doi_is_rejected_before_a_request(
    monkeypatch: pytest.MonkeyPatch,
    doi: str,
) -> None:
    requests = _install_responses(monkeypatch, [])

    with pytest.raises(ValueError, match="valid DOI"):
        await opencitations.get_opencitations_citation_edges(doi)

    assert requests == []


async def test_large_response_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _install_responses(
        monkeypatch,
        [
            httpx.Response(
                200,
                content=b"x" * (opencitations._MAX_RESPONSE_BYTES + 1),
            )
        ],
    )

    with pytest.raises(RuntimeError, match="1 MB limit"):
        await opencitations.get_opencitations_citation_edges(_DOI)

    assert len(requests) == 1


async def test_upstream_error_is_not_reported_as_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _install_responses(
        monkeypatch, [httpx.Response(503, json={"error": "unavailable"})]
    )

    with pytest.raises(RuntimeError, match=r"HTTPStatusError.*503"):
        await opencitations.get_opencitations_citation_edges(_DOI)

    assert len(requests) == 1


async def test_identifier_text_from_upstream_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _install_responses(
        monkeypatch,
        [
            [{"count": "1"}],
            [{"count": "0"}],
            [
                {
                    "oci": "1-2",
                    "citing": f"doi:10.1234/{'x' * 1024}",
                    "cited": f"doi:{_DOI}",
                }
            ],
        ],
    )

    with pytest.raises(RuntimeError, match="identifier text exceeds"):
        await opencitations.get_opencitations_citation_edges(_DOI)

    assert len(requests) == 3


async def test_index_prefixed_identifiers_keep_semicolons_inside_dois(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _install_responses(
        monkeypatch,
        [
            [{"count": "1"}],
            [{"count": "0"}],
            [
                {
                    "oci": "1-2",
                    "citing": (
                        "[COCI] => omid:br/1 doi:10.1234/citing;part; "
                        "[OCC] => pmid:42 doi:10.5678/other"
                    ),
                    "cited": (
                        f"[COCI] => doi:{_DOI}; "
                        "[OpenCitations] => openalex:W123"
                    ),
                }
            ],
        ],
    )

    result = await opencitations.get_opencitations_citation_edges(_DOI)

    edge = result["citations"]["edges"][0]
    assert edge["citing"] == [
        "omid:br/1",
        "doi:10.1234/citing;part",
        "pmid:42",
        "doi:10.5678/other",
    ]
    assert edge["cited"] == [f"doi:{_DOI}", "openalex:W123"]
    assert edge["citing_raw"].startswith("[COCI] =>")
    assert "[OCC] =>" in edge["citing_raw"]
    assert "[OpenCitations] =>" in edge["cited_raw"]
    assert len(requests) == 3


async def test_counts_precede_fetch_and_large_direction_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _install_responses(
        monkeypatch,
        [
            [{"count": "51"}],
            [{"count": "1"}],
            [
                {
                    "oci": "1-2",
                    "citing": f"doi:{_DOI}",
                    "cited": "doi:10.1111/x",
                }
            ],
        ],
    )

    result = await opencitations.get_opencitations_citation_edges(_DOI)

    assert [
        url.partition("/index/v2/")[2].split("/", 1)[0] for url in requests
    ] == [
        "citation-count",
        "reference-count",
        "references",
    ]
    assert result["citations"]["edge_fetch_status"] == (
        "count_exceeds_edge_limit"
    )
    assert result["citations"]["edges"] == []
    assert result["citations"]["edge_request_url"] is None
    assert result["references"]["edge_request_url"] == requests[2]
    assert result["accessed_at"].endswith("+00:00")


def test_concurrent_requests_reserve_one_second_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(opencitations, "_next_request_at", 0.0)
    now = 100.0
    with ThreadPoolExecutor(max_workers=12) as pool:
        slots = list(
            pool.map(
                lambda _: opencitations._reserve_request_at(now), range(24)
            )
        )

    assert sorted(slots) == pytest.approx(
        [now + offset for offset in range(24)]
    )
