"""The group's papers as a search source that survives an MCP outage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from co_scientist.research import RetrievalError
from co_scientist.research_adapter.composite import ResearchRetrieval
from co_scientist.research_adapter.local_corpus import (
    GROUP_CORPUS_SOURCE,
    LocalCorpusRetrieval,
    corpus_root,
    corpus_search_permitted,
    local_corpus_for,
)
from co_scientist.research_adapter.retrieval import McpRetrieval

_PAPERS = [
    {
        "paper_id": "raf-inhibitor-resistance",
        "title": "Conformation-specific RAF inhibitors overcome resistance",
        "abstract": (
            "Combining conformation-specific RAF inhibitors overcomes "
            "acquired drug resistance in melanoma cells."
        ),
    },
    {
        "paper_id": "hif-network-model",
        "title": "A dynamic model of the HIF-1 network",
        "abstract": (
            "A dynamic model of the hypoxia inducible factor network "
            "predicts oxygen-dependent switching."
        ),
    },
]


def _corpus(tmp_path: Path, *, body: str | None = None) -> Path:
    """Write a two-paper corpus, optionally with one paper's full text."""
    root = tmp_path / "sbi"
    root.mkdir()
    (root / "catalog.json").write_text(
        json.dumps({"papers": _PAPERS}), encoding="utf-8"
    )
    if body is not None:
        (root / "raf-inhibitor-resistance.md").write_text(
            body, encoding="utf-8"
        )
    return root


class _Tool:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled


class _Registry:
    def __init__(self, tool: _Tool | None) -> None:
        self._tool = tool

    def get_tool(self, tool_id: str) -> _Tool | None:
        return self._tool


@pytest.mark.asyncio
async def test_a_question_finds_the_paper_that_answers_it(
    tmp_path: Path,
) -> None:
    """Ranking puts the on-topic paper first, with no network involved."""
    retrieval = LocalCorpusRetrieval(_corpus(tmp_path))

    hits = await retrieval.search(
        query="How is acquired RAF inhibitor resistance overcome?",
        source=GROUP_CORPUS_SOURCE,
        limit=5,
    )

    assert hits[0].locator == "raf-inhibitor-resistance"
    assert hits[0].title.startswith("Conformation-specific")
    # Better matches score higher, the way every other source reports it.
    assert all(
        hits[i].score >= hits[i + 1].score  # type: ignore[operator]
        for i in range(len(hits) - 1)
    )


@pytest.mark.asyncio
async def test_a_question_written_as_a_sentence_is_not_a_syntax_error(
    tmp_path: Path,
) -> None:
    """FTS5 syntax in a model-written question is data, not an expression.

    The queries reaching this port are written by a model as ordinary
    questions, and quotes, apostrophes and a stray capitalized OR are all
    ordinary English -- passed through raw, each is a query error that
    would read as "the corpus found nothing".
    """
    retrieval = LocalCorpusRetrieval(_corpus(tmp_path))

    hits = await retrieval.search(
        query='Does the "HIF-1" network OR NEAR(oxygen) switch?',
        source=GROUP_CORPUS_SOURCE,
        limit=5,
    )

    assert hits[0].locator == "hif-network-model"


@pytest.mark.asyncio
async def test_reading_a_paper_stays_inside_the_corpus(
    tmp_path: Path,
) -> None:
    """A crafted id cannot walk out of the corpus directory."""
    secret = tmp_path / "secret.md"
    secret.write_text("not a paper", encoding="utf-8")
    retrieval = LocalCorpusRetrieval(_corpus(tmp_path, body="# Full text"))

    assert await retrieval.read(locator="raf-inhibitor-resistance") == (
        "# Full text"
    )
    assert await retrieval.read(locator="../secret") is None


@pytest.mark.asyncio
async def test_a_paper_with_no_body_keeps_its_abstract(
    tmp_path: Path,
) -> None:
    """Three quarters of the catalog is abstract-only; that is not a failure.

    ``read`` answering None is what makes the loop fall back to the
    snippet, so an abstract-only paper is still a document it can draw a
    finding from rather than one it drops.
    """
    retrieval = LocalCorpusRetrieval(_corpus(tmp_path))

    assert await retrieval.read(locator="hif-network-model") is None


@pytest.mark.asyncio
async def test_another_source_is_refused_rather_than_answered(
    tmp_path: Path,
) -> None:
    """This port answers for one source and says so about any other."""
    retrieval = LocalCorpusRetrieval(_corpus(tmp_path))

    with pytest.raises(RetrievalError):
        await retrieval.search(query="x", source="pubmed", limit=3)


@pytest.mark.asyncio
async def test_a_query_with_nothing_searchable_in_it_is_a_failed_call(
    tmp_path: Path,
) -> None:
    """An empty expression must not silently match the whole corpus."""
    retrieval = LocalCorpusRetrieval(_corpus(tmp_path))

    with pytest.raises(RetrievalError):
        await retrieval.search(
            query="is it so?", source=GROUP_CORPUS_SOURCE, limit=3
        )


def test_the_audience_decision_is_read_and_not_restated() -> None:
    """Permission is the corpus tool's own enabled flag, nothing more.

    The app withholds the corpus tools from every audience but one. A
    second rule here would be a second gate to keep in step, and the one
    that gets forgotten is the one that leaks a lab's library.
    """
    assert corpus_search_permitted(_Registry(_Tool(enabled=True))) is True
    assert corpus_search_permitted(_Registry(_Tool(enabled=False))) is False
    assert corpus_search_permitted(_Registry(None)) is False


def test_a_directory_without_a_catalog_is_not_a_corpus(
    tmp_path: Path,
) -> None:
    """Most deployments ship no corpus; that is answered, not raised."""
    assert corpus_root(None) is None
    assert corpus_root(str(tmp_path)) is None
    assert corpus_root(str(_corpus(tmp_path))) is not None


def test_the_state_field_is_the_only_thing_a_node_has_to_ask(
    tmp_path: Path,
) -> None:
    """Both gates were resolved at setup, so a node reads one field."""
    root = _corpus(tmp_path)

    assert local_corpus_for({"local_corpus_dir": ""}) is None
    assert local_corpus_for({}) is None
    assert local_corpus_for({"local_corpus_dir": str(root)}) is not None


class _FakeMcp(McpRetrieval):
    """A remote half that answers one source.

    Subclasses the real port rather than duplicating its protocol: the
    composite distinguishes the two halves by type, so a structural
    stand-in would be routed as the local one and the test would pass
    for the wrong reason.
    """

    sources: tuple[str, ...] = ("pubmed",)

    def __init__(self) -> None:
        self.searched: list[str] = []

    async def search(self, *, query: str, source: str, limit: int) -> list[Any]:
        from co_scientist.research import SourceHit

        self.searched.append(source)
        return [SourceHit(locator="pm1", title="Remote", snippet="s", rank=0)]

    async def read(self, *, locator: str) -> str | None:
        return "remote text"

    def record(self, locator: str) -> dict[str, Any] | None:
        return {"title": "Remote", "source": "pubmed"}


@pytest.mark.asyncio
async def test_losing_the_search_server_leaves_the_corpus_searchable(
    tmp_path: Path,
) -> None:
    """The whole point: no remote half, and research still has a source."""
    composite = ResearchRetrieval(None, LocalCorpusRetrieval(_corpus(tmp_path)))

    assert composite.sources == (GROUP_CORPUS_SOURCE,)
    hits = await composite.search(
        query="RAF inhibitor resistance",
        source=GROUP_CORPUS_SOURCE,
        limit=3,
    )
    assert hits
    with pytest.raises(RetrievalError):
        await composite.search(query="x", source="pubmed", limit=3)


@pytest.mark.asyncio
async def test_a_document_is_read_by_whichever_port_returned_it(
    tmp_path: Path,
) -> None:
    """A locator is opaque, so only its own port can resolve it.

    Routing reads by source name instead would send a corpus paper_id to
    PubMed, which answers nothing -- and answering nothing is how the
    loop is told to fall back to a snippet, so the whole paper would be
    lost without any error.
    """
    remote = _FakeMcp()
    composite = ResearchRetrieval(
        remote, LocalCorpusRetrieval(_corpus(tmp_path, body="# Full text"))
    )

    await composite.search(query="resistance", source="pubmed", limit=3)
    await composite.search(
        query="RAF inhibitor resistance",
        source=GROUP_CORPUS_SOURCE,
        limit=3,
    )

    assert await composite.read(locator="pm1") == "remote text"
    assert await composite.read(locator="raf-inhibitor-resistance") == (
        "# Full text"
    )
    assert await composite.read(locator="never-seen") is None


@pytest.mark.asyncio
async def test_a_corpus_paper_reaches_the_pool_with_its_title(
    tmp_path: Path,
) -> None:
    """A corpus hit has no source metadata, so an equivalent is built.

    Callers turn findings into the review's paper records through
    ``record``; without one, a paper the run actually read would arrive
    titled by its id or be dropped entirely.
    """
    composite = ResearchRetrieval(
        _FakeMcp(), LocalCorpusRetrieval(_corpus(tmp_path))
    )
    await composite.search(
        query="HIF network", source=GROUP_CORPUS_SOURCE, limit=3
    )

    record = composite.record("hif-network-model")

    assert record is not None
    assert record["title"] == "A dynamic model of the HIF-1 network"
    assert record["source"] == GROUP_CORPUS_SOURCE
    assert composite.record("never-seen") is None


def test_sources_keep_the_network_ones_first(tmp_path: Path) -> None:
    """Order is the workflow's, with the local source appended.

    The loop searches sources in the order it is given them, so putting
    the corpus first would spend a level's breadth on one lab's library
    before any public database was asked.
    """
    composite = ResearchRetrieval(
        _FakeMcp(), LocalCorpusRetrieval(_corpus(tmp_path))
    )

    assert composite.sources == ("pubmed", GROUP_CORPUS_SOURCE)
