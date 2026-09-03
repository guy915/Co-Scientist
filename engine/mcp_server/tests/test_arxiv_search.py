"""Tests for arXiv search."""

import httpx
import pytest
from mcp_server.tests._httpx import stub_failure, stub_responses
from mcp_server.tools.lit_review import arxiv_search

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
    """Builds one arXiv Atom feed response with a single entry.

    Args:
        doi: An ``<arxiv:doi>`` element to include, or "" to omit it --
            most preprints have no published DOI.
    """
    doi_element = f"<arxiv:doi>{doi}</arxiv:doi>" if doi else ""
    return _FEED_TEMPLATE.format(doi=doi_element)


async def test_a_real_feed_normalizes_to_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A realistic Atom response yields a non-empty, cleaned-up record."""
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


async def test_every_record_carries_a_stable_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The engine re-keys a list-shaped response by each record's own id.

    Without a stable id, results from a second query would overwrite the
    first's at the same list position (see europepmc_search's analogous
    test for the incident this guards against).
    """
    stub_responses(monkeypatch, _feed())

    result = await arxiv_search.search_arxiv("resistance reversal")

    assert result["records"][0]["source_id"] == "2401.01234"


async def test_the_source_id_drops_the_revision_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later version of the same submission is still the same paper."""
    stub_responses(monkeypatch, _feed())

    result = await arxiv_search.search_arxiv("resistance reversal")

    assert "v2" not in result["records"][0]["source_id"]


async def test_a_missing_doi_is_none_not_a_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Most preprints have no journal DOI; the field is still present."""
    stub_responses(monkeypatch, _feed(doi=""))

    result = await arxiv_search.search_arxiv("resistance reversal")

    assert result["records"][0]["doi"] is None


async def test_a_failed_request_degrades_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One unreachable source must not fail a step consulting several."""
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
    """A public HTTP endpoint's bad or truncated body must not crash.

    Same degrade path as a transport failure below.
    """
    stub_responses(monkeypatch, "<feed><entry><title>unterminated")

    result = await arxiv_search.search_arxiv("resistance reversal")

    assert result["records"] == []


async def test_an_entry_with_no_id_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An error query answers as one entry with no <id>.

    Treating that as a paper would surface a synthetic empty-titled
    record instead of the honest empty-records envelope.
    """
    stub_responses(
        monkeypatch,
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        "<entry><title>error</title></entry>"
        "</feed>",
    )

    result = await arxiv_search.search_arxiv("resistance reversal")

    assert result["records"] == []
