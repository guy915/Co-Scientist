"""Tests for the local paper-corpus search tool.

The real corpus is git-ignored publisher content, so each test builds its
own in a temp directory and points the tool at it.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from mcp_server.tools.lit_review import search_paper_corpus as module
from mcp_server.tools.lit_review.search_paper_corpus import search_paper_corpus


@pytest.fixture(autouse=True)
def _clear_index() -> Iterator[None]:
    """The index is cached per process, so drop it around every test."""
    module._index.cache_clear()
    yield
    module._index.cache_clear()


@pytest.fixture()
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "mapk.md").write_text(
        "# MAPK Feedback Paper\n\n"
        + "Trametinib inhibits MEK and relieves ERK negative feedback. " * 40,
        encoding="utf-8",
    )
    (root / "stat3.md").write_text(
        "# STAT3 Paper\n\n"
        + "STAT3 phosphorylation at Y705 drives survivin expression. " * 40,
        encoding="utf-8",
    )
    monkeypatch.setenv(module.CORPUS_ENV_VAR, str(root))
    return root


def test_returns_passages_from_the_matching_paper(corpus: Path) -> None:
    results = json.loads(search_paper_corpus("trametinib MEK feedback", 3))
    assert results
    first = next(iter(results.values()))
    assert first["title"] == "MAPK Feedback Paper"
    # Passages, not whole papers: a hit has to fit in a prompt.
    assert 0 < len(first["abstract"]) < 4000


def test_respects_the_passage_limit(corpus: Path) -> None:
    assert len(json.loads(search_paper_corpus("STAT3 survivin", 1))) == 1


def test_absent_corpus_returns_empty_rather_than_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No corpus is the default state; the agent should fall back to PubMed."""
    monkeypatch.delenv(module.CORPUS_ENV_VAR, raising=False)
    assert json.loads(search_paper_corpus("anything at all")) == {}


def test_unmatched_query_returns_empty(corpus: Path) -> None:
    assert json.loads(search_paper_corpus("zzzz nonexistent term")) == {}


def test_results_are_deterministic(corpus: Path) -> None:
    """Ties break on position, so repeated calls agree."""
    once = search_paper_corpus("phosphorylation", 5)
    module._index.cache_clear()
    assert search_paper_corpus("phosphorylation", 5) == once
