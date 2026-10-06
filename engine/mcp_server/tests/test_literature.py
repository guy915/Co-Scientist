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


async def test_an_arxiv_error_entry_without_an_id_is_not_a_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Query errors can look like entries; admitting them invents empty-titled
    # papers.
    stub_responses(
        monkeypatch,
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        "<entry><title>error</title></entry></feed>",
    )

    result = await arxiv_search.search_arxiv("resistance reversal")

    assert result["records"] == []


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


async def test_openalex_failure_raises_instead_of_looking_like_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_responses(monkeypatch, StubResponse(None, error=httpx.HTTPError("x")))

    with pytest.raises(OpenAlexUnavailableError, match="could not be"):
        await search_openalex("q")


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
