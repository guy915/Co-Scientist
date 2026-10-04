import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from httpx import ASGITransport, AsyncClient
from mcp_server.campaign import PUBLIC_TOOLS
from mcp_server.server import mcp
from mcp_server.tests._httpx import (
    StubClient,
    StubResponse,
    stub_failure,
    stub_responses,
)
from mcp_server.tools.lit_review import (
    arxiv_search,
    europepmc_search,
    opencitations,
)
from mcp_server.tools.lit_review.openalex_search import (
    OpenAlexUnavailableError,
    _build_search_params,
    normalize_works,
    search_openalex,
)
from starlette.applications import Starlette

_FEED_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.01234v2</id>
    <published>2024-01-15T10:00:00Z</published>
    <title>  A Model of
      Resistance Reversal  </title>
    <summary>An abstract that
      wraps across lines.</summary>
    <author><name>Jane Doe</name></author>
    <author><name>John Smith</name></author>
    {doi}
  </entry>
</feed>"""


def _feed(doi: str = "") -> str:
    doi_element = f"<arxiv:doi>{doi}</arxiv:doi>" if doi else ""
    return _FEED_TEMPLATE.format(doi=doi_element)


async def test_a_real_feed_normalizes_to_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_responses(monkeypatch, _feed(doi="10.1234/foo"))

    result = await arxiv_search.search_arxiv("resistance reversal")

    assert result["source"] == "arXiv"
    assert result["query"] == "resistance reversal"
    (record,) = result["records"]
    assert record["title"] == "A Model of Resistance Reversal"
    assert record["abstract"] == "An abstract that wraps across lines."
    assert record["year"] == 2024
    assert record["authors"] == ["Jane Doe", "John Smith"]
    assert record["doi"] == "10.1234/foo"
    assert record["is_preprint"] is True
    assert record["url"] == "http://arxiv.org/abs/2401.01234v2"


async def test_the_source_id_drops_the_revision_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_responses(monkeypatch, _feed())

    result = await arxiv_search.search_arxiv("resistance reversal")

    assert "v2" not in result["records"][0]["source_id"]


async def test_a_missing_doi_is_none_not_a_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_responses(monkeypatch, _feed(doi=""))

    result = await arxiv_search.search_arxiv("resistance reversal")

    assert result["records"][0]["doi"] is None


async def test_a_failed_request_degrades_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_failure(monkeypatch, httpx.ConnectError("boom"))

    result = await arxiv_search.search_arxiv("resistance reversal")

    assert result == {
        "source": "arXiv",
        "query": "resistance reversal",
        "records": [],
    }


async def test_malformed_xml_degrades_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_responses(monkeypatch, "<feed><entry><title>unterminated")

    result = await arxiv_search.search_arxiv("resistance reversal")

    assert result["records"] == []


async def test_an_entry_with_no_id_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Query errors can look like entries; admitting them invents empty-
    titled papers."""
    stub_responses(
        monkeypatch,
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        "<entry><title>error</title></entry>"
        "</feed>",
    )

    result = await arxiv_search.search_arxiv("resistance reversal")

    assert result["records"] == []


class TestArxivSearch:
    async def test_every_record_carries_a_stable_identifier(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Position-based ids let a later query overwrite unrelated earlier
        results."""
        stub_responses(monkeypatch, _feed())

        result = await arxiv_search.search_arxiv("resistance reversal")

        assert result["records"][0]["source_id"] == "2401.01234"


@pytest.fixture
def _no_retry_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        europepmc_search, "_TRANSPORT_RETRY_DELAYS_SECONDS", (0.0, 0.0)
    )


def _payload(source: str = "MED", **overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "id": "42387642",
        "source": source,
        "title": "PKMYT1 in Cancer",
        "abstractText": "PKMYT1 has emerged as a target.",
        "pubYear": "2026",
        "doi": "10.1002/gcc.70151",
        "authorString": "Li Y, Chen X.",
        "citedByCount": 3,
    }
    return {"resultList": {"result": [result | overrides]}}


@pytest.mark.usefixtures("_no_retry_wait")
class TestEuropepmcSearch:
    async def test_a_result_says_whether_it_was_peer_reviewed(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Europe PMC mixes preprints and published articles; peer-review
        status changes evidence strength."""
        stub_responses(monkeypatch, _payload(source="PPR"))

        result = await europepmc_search.search_europepmc("PKMYT1")

        (record,) = result["records"]
        assert record["is_preprint"] is True
        assert record["doi"] == "10.1002/gcc.70151"
        assert record["url"] == "https://doi.org/10.1002/gcc.70151"

    async def test_a_journal_article_is_not_flagged_as_a_preprint(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        stub_responses(monkeypatch, _payload(source="MED"))

        result = await europepmc_search.search_europepmc("PKMYT1")

        assert result["records"][0]["is_preprint"] is False

    async def test_preprint_search_restricts_the_query_to_preprint_servers(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """bioRxiv cannot search by topic; Europe PMC source filtering
        supplies that restriction."""
        client = stub_responses(monkeypatch, _payload(source="PPR"))

        await europepmc_search.search_preprints("PKMYT1")

        (_, params) = client.calls[0]
        assert params["query"] == "(PKMYT1) AND SRC:PPR"

    async def test_biorxiv_search_restricts_to_biorxiv_specifically(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = stub_responses(monkeypatch, _payload(source="PPR"))

        await europepmc_search.search_biorxiv("PKMYT1")

        (_, params) = client.calls[0]
        assert params["query"] == (
            '(PKMYT1) AND SRC:PPR AND PUBLISHER:"bioRxiv"'
        )

    async def test_biorxiv_search_echoes_the_query_without_the_filter(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        stub_responses(monkeypatch, _payload(source="PPR"))

        result = await europepmc_search.search_biorxiv("PKMYT1")

        assert result["query"] == "PKMYT1"
        assert result["source"] == "bioRxiv"

    @pytest.mark.parametrize(
        ("tool", "source"),
        [
            (europepmc_search.search_europepmc, "Europe PMC"),
            (europepmc_search.search_preprints, "Preprints"),
            (europepmc_search.search_biorxiv, "bioRxiv"),
        ],
    )
    async def test_a_failed_request_is_distinct_from_an_empty_search(
        self, monkeypatch: pytest.MonkeyPatch, tool: object, source: str
    ) -> None:
        """An unreachable source must remain distinguishable from a
        successful empty result."""
        stub_failure(monkeypatch, httpx.ConnectError("boom"))

        with pytest.raises(RuntimeError, match=source):
            await tool("PKMYT1")  # type: ignore[operator]

    async def test_every_record_carries_a_stable_identifier(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Position-based ids let a later query overwrite unrelated earlier
        results."""
        stub_responses(monkeypatch, _payload())

        result = await europepmc_search.search_europepmc(
            "pkmyt1", max_results=1
        )

        assert result["records"][0]["source_id"] == "MED/42387642"

    async def test_biorxiv_search_returns_a_normalized_record(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        stub_responses(monkeypatch, _payload(source="PPR"))

        result = await europepmc_search.search_biorxiv("pkmyt1", max_results=1)

        (record,) = result["records"]
        assert record["source_id"] == "PPR/42387642"
        assert record["title"] == "PKMYT1 in Cancer"
        assert record["is_preprint"] is True

    async def test_citation_count_uses_the_name_the_ranker_reads(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        stub_responses(monkeypatch, _payload())

        result = await europepmc_search.search_europepmc(
            "pkmyt1", max_results=1
        )

        assert result["records"][0]["cited_by_count"] == 3

    async def test_a_record_reads_as_plain_text(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        stub_responses(
            monkeypatch,
            _payload(
                title="Colistin resistance in &lt;i&gt;K. pneumoniae&lt;/i&gt;",
                abstractText="<h4>Aims</h4><i>K. pneumoniae</i> is a threat.",
            ),
        )

        search = await europepmc_search.search_europepmc("colistin")

        (record,) = search["records"]
        assert record["title"] == "Colistin resistance in K. pneumoniae"
        assert record["abstract"] == "Aims K. pneumoniae is a threat."

    @pytest.mark.parametrize(
        "payload",
        [
            None,
            [],
            {},
            {"resultList": []},
            {"resultList": {"result": "invalid"}},
            {"resultList": {"result": [None]}},
        ],
    )
    async def test_malformed_response_is_not_an_empty_search(
        self, monkeypatch: pytest.MonkeyPatch, payload: object
    ) -> None:
        stub_responses(monkeypatch, payload)
        with pytest.raises(RuntimeError, match="Europe PMC"):
            await europepmc_search.search_europepmc("PKMYT1")

    async def test_valid_empty_response_remains_an_empty_search(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        stub_responses(monkeypatch, {"resultList": {"result": []}})
        assert await europepmc_search.search_europepmc("unlikely query") == {
            "source": "Europe PMC",
            "query": "unlikely query",
            "records": [],
        }

    async def test_rate_limit_retains_status_and_retry_hint(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        request = httpx.Request(
            "GET", "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        )
        response = httpx.Response(
            429, request=request, headers={"Retry-After": "60"}
        )
        stub_failure(
            monkeypatch,
            httpx.HTTPStatusError(
                "throttled", request=request, response=response
            ),
        )
        with pytest.raises(RuntimeError, match="HTTP 429; Retry-After=60"):
            await europepmc_search.search_preprints("PKMYT1")

    async def test_a_dropped_connection_is_retried_on_a_fresh_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        responses: list[object] = [
            httpx.RemoteProtocolError("Server disconnected"),
            _payload(),
        ]

        class _FlakyClient(StubClient):
            def _serve(self, url: str, payload: object) -> StubResponse:
                self.calls.append((url, payload))
                outcome = responses.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return StubResponse(outcome)

        client = _FlakyClient()
        monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)

        result = await europepmc_search.search_biorxiv("PKMYT1")

        assert len(client.calls) == 2
        assert result["records"][0]["title"] == "PKMYT1 in Cancer"

    async def test_a_persistent_transport_failure_still_fails_the_source(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = stub_failure(
            monkeypatch, httpx.RemoteProtocolError("Server disconnected")
        )

        with pytest.raises(RuntimeError, match="RemoteProtocolError"):
            await europepmc_search.search_europepmc("PKMYT1")

        assert len(client.calls) == 3


_SAMPLE: dict[str, Any] = {
    "results": [
        {
            "id": "https://openalex.org/W123",
            "title": "Ambient nitrogen fixation",
            "publication_year": 2023,
            "authorships": [
                {"author": {"display_name": "Ada Lovelace"}},
                {"author": {"display_name": "Alan Turing"}},
            ],
            "abstract_inverted_index": {
                "Nitrogen": [0],
                "fixation": [1],
                "matters": [2],
            },
            "primary_location": {"landing_page_url": "https://example/w123"},
            "doi": "https://doi.org/10.1/x",
        },
        {
            "id": "https://openalex.org/W456",
            "display_name": "Second work",
            "publication_year": 2020,
            "authorships": [],
            "abstract_inverted_index": None,
            "primary_location": {},
            "doi": "https://doi.org/10.2/y",
        },
    ]
}


def test_normalize_basic_fields() -> None:
    out = normalize_works(_SAMPLE, max_papers=10)
    assert set(out) == {"W123", "W456"}
    w = out["W123"]
    assert w["title"] == "Ambient nitrogen fixation"
    assert w["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert w["year"] == 2023
    assert w["abstract"] == "Nitrogen fixation matters"
    assert w["url"] == "https://example/w123"
    assert w["source"] == "openalex"
    assert w["is_retracted"] is False


def test_normalize_falls_back_to_doi_url_and_display_name() -> None:
    out = normalize_works(_SAMPLE, max_papers=10)
    w = out["W456"]
    assert w["title"] == "Second work"
    assert w["abstract"] == ""
    assert w["url"] == "https://doi.org/10.2/y"


def test_normalize_caps_results() -> None:
    out = normalize_works(_SAMPLE, max_papers=1)
    assert len(out) == 1


def test_normalize_handles_garbage() -> None:
    assert normalize_works({}, 10) == {}
    assert normalize_works({"results": "nope"}, 10) == {}
    assert normalize_works({"results": [None, 7]}, 10) == {}


class _FakeResp:
    def __init__(self, data: Any, raise_exc: Exception | None = None) -> None:
        self._data = data
        self._raise = raise_exc

    def raise_for_status(self) -> None:
        if self._raise is not None:
            raise self._raise

    def json(self) -> Any:
        return self._data


class _FakeClient:
    def __init__(self, resp: _FakeResp) -> None:
        self._resp = resp

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False

    async def get(self, _url: str, params: Any = None) -> _FakeResp:
        return self._resp


class _PagedClient:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self._pages = iter(pages)
        self.cursors: list[str] = []

    async def __aenter__(self) -> "_PagedClient":
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False

    async def get(self, _url: str, params: Any = None) -> _FakeResp:
        self.cursors.append(str(params["cursor"]))
        return _FakeResp(next(self._pages))


def test_search_openalex_returns_normalized(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_: _FakeClient(_FakeResp(_SAMPLE)),
    )
    out = asyncio.run(search_openalex("nitrogen fixation", max_papers=5))
    assert "W123" in out
    assert out["W123"]["source"] == "openalex"


def test_search_openalex_raises_when_it_cannot_be_asked(
    monkeypatch: Any,
) -> None:
    """Source refusal is not a successful empty search and must preserve
    failure provenance."""
    err = httpx.HTTPError("boom")
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_: _FakeClient(_FakeResp(None, raise_exc=err)),
    )

    with pytest.raises(OpenAlexUnavailableError, match="could not be"):
        asyncio.run(search_openalex("q"))


def test_a_rate_limit_says_how_long_and_why(monkeypatch: Any) -> None:
    response = httpx.Response(
        429,
        headers={"retry-after": "6810"},
        json={"error": "Rate limit exceeded", "message": "Insufficient budget"},
        request=httpx.Request("GET", "https://api.openalex.org/works"),
    )
    err = httpx.HTTPStatusError(
        "429", request=response.request, response=response
    )
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_: _FakeClient(_FakeResp(None, raise_exc=err)),
    )

    with pytest.raises(OpenAlexUnavailableError) as raised:
        asyncio.run(search_openalex("q"))

    message = str(raised.value)
    assert "HTTP 429" in message
    assert "Insufficient budget" in message
    assert "retry after 6810s" in message


def test_no_match_is_still_an_empty_result(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_: _FakeClient(_FakeResp({"results": [], "meta": {}})),
    )

    assert asyncio.run(search_openalex("q")) == {}


def test_search_openalex_uses_cursor_pagination(monkeypatch: Any) -> None:
    second = {
        "results": [
            {
                "id": "https://openalex.org/W789",
                "title": "Third work",
            }
        ],
        "meta": {"next_cursor": None},
    }
    first = {**_SAMPLE, "meta": {"next_cursor": "cursor-2"}}
    client = _PagedClient([first, second])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)

    out = asyncio.run(search_openalex("nitrogen fixation", max_papers=3))

    assert set(out) == {"W123", "W456", "W789"}
    assert client.cursors == ["*", "cursor-2"]


def test_search_params_exclude_retractions_and_support_api_key(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("OPENALEX_API_KEY", "key")
    params, per_page = _build_search_params("q", 250, 5)

    assert per_page == 100
    assert params["cursor"] == "*"
    assert params["api_key"] == "key"
    assert "is_retracted:false" in params["filter"]


def test_wildcards_are_stripped_before_reaching_openalex() -> None:
    """OpenAlex rejects wildcard terms on the ordinary search parameter."""
    params, _ = _build_search_params(
        "glioblastoma repurpos* drug?", max_papers=10, recency_years=0
    )

    assert "*" not in params["search"]
    assert "?" not in params["search"]
    assert params["search"] == "glioblastoma repurpos drug"


def test_wildcard_stripping_collapses_the_resulting_whitespace() -> None:
    params, _ = _build_search_params("a* * b", max_papers=10, recency_years=0)

    assert params["search"] == "a b"


def test_a_clean_query_is_untouched() -> None:
    params, _ = _build_search_params(
        '"exact phrase" AND glioblastoma', max_papers=10, recency_years=0
    )

    assert params["search"] == '"exact phrase" AND glioblastoma'


_REAL_ASYNC_CLIENT = httpx.AsyncClient
_MOCK_TRANSPORT = httpx.MockTransport
_DOI = "10.1108/jd-12-2013-0166"


async def _no_wait_for_slot() -> None:
    """Fake HTTP responses must not wait for the process-wide real-network
    pacer."""


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
        httpx,
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
        httpx,
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


async def test_edge_count_growth_cannot_appear_complete_after_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {"oci": f"{index}-2", "citing": f"doi:{_DOI}", "cited": "doi:10.1111/x"}
        for index in range(1, 52)
    ]
    requests = _install_responses(
        monkeypatch,
        [[{"count": "50"}], [{"count": "0"}], rows],
    )

    with pytest.raises(RuntimeError, match="edge count exceeds"):
        await opencitations.get_opencitations_citation_edges(_DOI)

    assert len(requests) == 3


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
