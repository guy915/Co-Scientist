from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import pytest
from mcp_server.campaign import PUBLIC_TOOLS
from mcp_server.tests._httpx import (
    StubResponse,
    registered_tools,
    stub_failure,
    stub_responses,
    transport_responses,
)
from mcp_server.tools.lit_review import (
    arxiv_search,
    europepmc_search,
    opencitations,
)
from mcp_server.tools.lit_review.openalex_search import (
    OpenAlexUnavailableError,
    search_openalex,
)

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


@pytest.mark.parametrize("doi", ["10.1234/foo", None])
async def test_an_arxiv_feed_normalizes_to_records(
    monkeypatch: pytest.MonkeyPatch, doi: str | None
) -> None:
    stub_responses(monkeypatch, _feed(doi=doi or ""))

    result = await arxiv_search.search_arxiv("resistance reversal")

    assert result["source"] == "arXiv"
    assert result["query"] == "resistance reversal"
    (record,) = result["records"]
    assert record["title"] == "A Model of Resistance Reversal"
    assert record["abstract"] == "An abstract that wraps across lines."
    assert record["year"] == 2024
    assert record["authors"] == ["Jane Doe", "John Smith"]
    assert record["doi"] == doi
    assert record["is_preprint"] is True
    assert record["url"] == "http://arxiv.org/abs/2401.01234v2"
    # Position-based ids let a later query overwrite unrelated results.
    assert record["source_id"] == "2401.01234"


@pytest.mark.parametrize(
    "response",
    [
        httpx.ConnectError("boom"),
        "<feed><entry><title>unterminated",
        # Query errors can look like entries; admitting them invents
        # empty-titled papers.
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        "<entry><title>error</title></entry></feed>",
    ],
    ids=["failed request", "malformed xml", "entry without an id"],
)
async def test_an_unusable_arxiv_response_degrades_to_no_records(
    monkeypatch: pytest.MonkeyPatch, response: Exception | str
) -> None:
    if isinstance(response, Exception):
        stub_failure(monkeypatch, response)
    else:
        stub_responses(monkeypatch, response)

    assert await arxiv_search.search_arxiv("resistance reversal") == {
        "source": "arXiv",
        "query": "resistance reversal",
        "records": [],
    }


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
    @pytest.mark.parametrize(
        ("source", "preprint"), [("PPR", True), ("MED", False)]
    )
    async def test_a_record_says_whether_it_was_peer_reviewed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        source: str,
        preprint: bool,
    ) -> None:
        stub_responses(monkeypatch, _payload(source=source))

        result = await europepmc_search.search_europepmc("PKMYT1")

        (record,) = result["records"]
        assert record["is_preprint"] is preprint
        assert record["source_id"] == f"{source}/42387642"
        assert record["doi"] == "10.1002/gcc.70151"
        assert record["url"] == "https://doi.org/10.1002/gcc.70151"
        assert record["cited_by_count"] == 3

    @pytest.mark.parametrize(
        ("tool", "label", "europepmc_query"),
        [
            (
                europepmc_search.search_preprints,
                "Preprints",
                "(PKMYT1) AND SRC:PPR",
            ),
            (
                europepmc_search.search_biorxiv,
                "bioRxiv",
                '(PKMYT1) AND SRC:PPR AND PUBLISHER:"bioRxiv"',
            ),
        ],
    )
    async def test_preprint_searches_restrict_the_query_to_their_servers(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tool: Any,
        label: str,
        europepmc_query: str,
    ) -> None:
        client = stub_responses(monkeypatch, _payload(source="PPR"))

        result = await tool("PKMYT1")

        assert client.calls[0][1]["query"] == europepmc_query
        assert result["query"] == "PKMYT1"
        assert result["source"] == label
        assert result["records"][0]["is_preprint"] is True

    @pytest.mark.parametrize(
        ("tool", "source"),
        [
            (europepmc_search.search_europepmc, "Europe PMC"),
            (europepmc_search.search_preprints, "Preprints"),
            (europepmc_search.search_biorxiv, "bioRxiv"),
        ],
    )
    async def test_a_failed_request_is_distinct_from_an_empty_search(
        self, monkeypatch: pytest.MonkeyPatch, tool: Any, source: str
    ) -> None:
        stub_failure(monkeypatch, httpx.ConnectError("boom"))

        with pytest.raises(RuntimeError, match=source):
            await tool("PKMYT1")

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
        client = stub_responses(
            monkeypatch,
            httpx.RemoteProtocolError("Server disconnected"),
            _payload(),
        )

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


async def test_openalex_works_normalize_with_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_responses(monkeypatch, _SAMPLE)

    out = await search_openalex("nitrogen fixation", max_papers=5)

    assert set(out) == {"W123", "W456"}
    assert out["W123"] == out["W123"] | {
        "title": "Ambient nitrogen fixation",
        "authors": ["Ada Lovelace", "Alan Turing"],
        "year": 2023,
        "abstract": "Nitrogen fixation matters",
        "url": "https://example/w123",
        "source": "openalex",
        "is_retracted": False,
    }
    assert out["W456"] == out["W456"] | {
        "title": "Second work",
        "abstract": "",
        "url": "https://doi.org/10.2/y",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"results": "nope"},
        {"results": [None, 7]},
        {"results": [], "meta": {}},
    ],
)
async def test_openalex_no_usable_works_is_an_empty_result(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> None:
    stub_responses(monkeypatch, payload)

    assert await search_openalex("q") == {}


async def test_openalex_failure_raises_instead_of_looking_like_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_responses(monkeypatch, StubResponse(None, error=httpx.HTTPError("x")))

    with pytest.raises(OpenAlexUnavailableError, match="could not be"):
        await search_openalex("q")


async def test_a_rate_limit_says_how_long_and_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = httpx.Response(
        429,
        headers={"retry-after": "6810"},
        json={"error": "Rate limit exceeded", "message": "Insufficient budget"},
        request=httpx.Request("GET", "https://api.openalex.org/works"),
    )
    err = httpx.HTTPStatusError(
        "429", request=response.request, response=response
    )
    stub_responses(monkeypatch, StubResponse(None, error=err))

    with pytest.raises(OpenAlexUnavailableError) as raised:
        await search_openalex("q")

    message = str(raised.value)
    assert "HTTP 429" in message
    assert "Insufficient budget" in message
    assert "retry after 6810s" in message


async def test_openalex_follows_cursor_pages_and_excludes_retractions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENALEX_API_KEY", "key")
    second = {
        "results": [{"id": "https://openalex.org/W789", "title": "Third work"}],
        "meta": {"next_cursor": None},
    }
    first = {**_SAMPLE, "meta": {"next_cursor": "cursor-2"}}
    client = stub_responses(monkeypatch, first, second)

    out = await search_openalex(
        "nitrogen fixation", max_papers=3, recency_years=5
    )
    capped = stub_responses(monkeypatch, first)
    assert len(await search_openalex("nitrogen fixation", max_papers=1)) == 1

    assert set(out) == {"W123", "W456", "W789"}
    assert [str(params["cursor"]) for _, params in client.calls] == [
        "*",
        "cursor-2",
    ]
    assert client.calls[0][1]["api_key"] == "key"
    assert "is_retracted:false" in client.calls[0][1]["filter"]
    assert "from_publication_date:" in client.calls[0][1]["filter"]
    assert len(capped.calls) == 1


@pytest.mark.parametrize(
    ("query", "sent"),
    [
        ("glioblastoma repurpos* drug?", "glioblastoma repurpos drug"),
        ("a* * b", "a b"),
        ('"exact phrase" AND glioblastoma', '"exact phrase" AND glioblastoma'),
    ],
)
async def test_wildcards_are_stripped_before_reaching_openalex(
    monkeypatch: pytest.MonkeyPatch, query: str, sent: str
) -> None:
    client = stub_responses(monkeypatch, {"results": []})

    await search_openalex(query)

    assert client.calls[0][1]["search"] == sent


_DOI = "10.1108/jd-12-2013-0166"


async def _no_wait_for_slot() -> None:
    """Fake HTTP responses must not wait for the process-wide real-network
    pacer."""


def _install_responses(
    monkeypatch: pytest.MonkeyPatch, responses: list[Any]
) -> list[httpx.Request]:
    requests = transport_responses(monkeypatch, *responses)
    monkeypatch.setattr(
        opencitations, "_wait_for_request_slot", _no_wait_for_slot
    )
    return requests


async def test_citation_edges_is_available_on_the_mcp_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _install_responses(
        monkeypatch,
        [
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
        ],
    )
    tool_name = "get_opencitations_citation_edges"

    async with registered_tools() as client:
        tools = await client.list_tools()
        result = await client.call_tool(tool_name, {"doi": _DOI})

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
    assert result.data["citations"]["edge_request_url"] == str(requests[2].url)
    assert result.data["references"]["edge_request_url"] == str(requests[3].url)
    assert "do not establish" in result.data["interpretation_note"]
    assert len(requests) == 4


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


@pytest.mark.parametrize(
    "doi", ["https://example.com/not-a-doi", "10.1234/" + ("x" * 257)]
)
async def test_invalid_doi_is_rejected_before_a_request(
    monkeypatch: pytest.MonkeyPatch,
    doi: str,
) -> None:
    requests = _install_responses(monkeypatch, [])

    with pytest.raises(ValueError, match="valid DOI"):
        await opencitations.get_opencitations_citation_edges(doi)

    assert requests == []


_ONE_EDGE = {"oci": "1-2", "citing": f"doi:{_DOI}", "cited": "doi:10.1111/x"}


@pytest.mark.parametrize(
    ("responses", "error", "request_count"),
    [
        pytest.param(
            [
                httpx.Response(
                    200, content=b"x" * (opencitations._MAX_RESPONSE_BYTES + 1)
                )
            ],
            "1 MB limit",
            1,
            id="large response",
        ),
        pytest.param(
            [
                [{"count": "50"}],
                [{"count": "0"}],
                [{**_ONE_EDGE, "oci": f"{n}-2"} for n in range(1, 52)],
            ],
            "edge count exceeds",
            3,
            id="edge count grew past the limit",
        ),
        pytest.param(
            [httpx.Response(503, json={"error": "unavailable"})],
            r"HTTPStatusError.*503",
            1,
            id="upstream error is not reported as zero",
        ),
        pytest.param(
            [
                [{"count": "1"}],
                [{"count": "0"}],
                [{**_ONE_EDGE, "citing": f"doi:10.1234/{'x' * 1024}"}],
            ],
            "identifier text exceeds",
            3,
            id="identifier text is bounded",
        ),
    ],
)
async def test_unusable_upstream_answers_fail_instead_of_looking_complete(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[Any],
    error: str,
    request_count: int,
) -> None:
    requests = _install_responses(monkeypatch, responses)

    with pytest.raises(RuntimeError, match=error):
        await opencitations.get_opencitations_citation_edges(_DOI)

    assert len(requests) == request_count


async def test_index_prefixed_identifiers_keep_semicolons_inside_dois(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_responses(
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


async def test_counts_precede_fetch_and_large_direction_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _install_responses(
        monkeypatch, [[{"count": "51"}], [{"count": "1"}], [_ONE_EDGE]]
    )

    result = await opencitations.get_opencitations_citation_edges(_DOI)

    assert [
        str(request.url).partition("/index/v2/")[2].split("/", 1)[0]
        for request in requests
    ] == ["citation-count", "reference-count", "references"]
    assert result["citations"]["edge_fetch_status"] == (
        "count_exceeds_edge_limit"
    )
    assert result["citations"]["edges"] == []
    assert result["citations"]["edge_request_url"] is None
    assert result["references"]["edge_request_url"] == str(requests[2].url)


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
