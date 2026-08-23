"""Tests for Europe PMC search and its preprint-restricted sibling."""

import httpx
import pytest
from mcp_server.tests._httpx import stub_failure, stub_responses
from mcp_server.tools.lit_review import europepmc_search


def _payload(source: str = "MED") -> dict[str, object]:
    """Builds one Europe PMC search response with a single result."""
    return {
        "resultList": {
            "result": [
                {
                    "id": "42387642",
                    "source": source,
                    "title": "PKMYT1 in Cancer",
                    "abstractText": "PKMYT1 has emerged as a target.",
                    "pubYear": "2026",
                    "doi": "10.1002/gcc.70151",
                    "authorString": "Li Y, Chen X.",
                    "citedByCount": 3,
                }
            ]
        }
    }


async def test_a_result_says_whether_it_was_peer_reviewed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Peer-review status is a fact about the evidence, not a detail.

    Europe PMC returns preprints alongside journal articles in one
    result list. A hypothesis citing an unreviewed preprint as if it were
    a published finding is overstating its support, so the flag travels
    with every record.
    """
    stub_responses(monkeypatch, _payload(source="PPR"))

    result = await europepmc_search.search_europepmc("PKMYT1")

    (record,) = result["records"]
    assert record["is_preprint"] is True
    assert record["doi"] == "10.1002/gcc.70151"
    assert record["url"] == "https://doi.org/10.1002/gcc.70151"


async def test_a_journal_article_is_not_flagged_as_a_preprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The flag has to distinguish, or it is not carrying information."""
    stub_responses(monkeypatch, _payload(source="MED"))

    result = await europepmc_search.search_europepmc("PKMYT1")

    assert result["records"][0]["is_preprint"] is False


async def test_preprint_search_restricts_the_query_to_preprint_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restricted at the query, since the corpus is one index.

    bioRxiv's own API can only list by posting date, so preprint
    *search* has to run through Europe PMC with its source filter --
    which means the restriction lives in the query string and would be
    silently lost if it were dropped.
    """
    client = stub_responses(monkeypatch, _payload(source="PPR"))

    await europepmc_search.search_preprints("PKMYT1")

    (_, params) = client.calls[0]
    assert params["query"] == "(PKMYT1) AND SRC:PPR"


@pytest.mark.parametrize(
    ("tool", "source"),
    [
        (europepmc_search.search_europepmc, "Europe PMC"),
        (europepmc_search.search_preprints, "Preprints"),
    ],
)
async def test_a_failed_request_degrades_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch, tool: object, source: str
) -> None:
    """One unreachable source must not fail a step consulting several."""
    stub_failure(monkeypatch, httpx.ConnectError("boom"))

    result = await tool("PKMYT1")  # type: ignore[operator]

    assert result == {"source": source, "query": "PKMYT1", "records": []}
