"""Tests for the local paper-corpus search and fetch tools.

Each test builds its own corpus in a temp directory rather than reading the
committed one, so behaviour is pinned to fixed inputs.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from mcp_server.tools.lit_review import search_paper_corpus as module
from mcp_server.tools.lit_review.search_paper_corpus import (
    fetch_paper,
    search_paper_corpus,
)


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


def test_a_weak_best_match_discards_the_whole_result(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kept in step with app.paper_corpus: judge the result by its best hit.

    Term-frequency scoring returns something for almost any query, so an
    agent asking "has this group studied X?" would always get passages back
    and could conclude they had.
    """
    assert json.loads(search_paper_corpus("trametinib MEK", 3))
    monkeypatch.setattr(module, "_MIN_TOP_SCORE", 10.0)
    module._index.cache_clear()
    assert json.loads(search_paper_corpus("trametinib MEK", 3)) == {}


def test_results_are_deterministic(corpus: Path) -> None:
    """Ties break on position, so repeated calls agree."""
    once = search_paper_corpus("phosphorylation", 5)
    module._index.cache_clear()
    assert search_paper_corpus("phosphorylation", 5) == once


def test_search_then_fetch_reads_the_whole_paper(corpus: Path) -> None:
    """The two tools compose: search locates, fetch reads.

    A passage is for deciding which paper matters; it is not the paper. An
    agent that finds a promising passage has to be able to read the rest.
    """
    hit = next(iter(json.loads(search_paper_corpus("trametinib", 1)).values()))
    full = json.loads(fetch_paper(hit["paper_id"]))
    body = next(iter(full.values()))
    assert body["title"] == hit["title"]
    # The whole paper, not the passage that led to it.
    assert len(body["content"]) > len(hit["abstract"])


def test_fetch_rejects_an_unknown_paper(corpus: Path) -> None:
    assert json.loads(fetch_paper("no-such-paper")) == {}


def test_fetch_refuses_to_escape_the_corpus_directory(
    corpus: Path, tmp_path: Path
) -> None:
    """A paper_id is model output, so it is treated as untrusted input."""
    (tmp_path / "secret.md").write_text("# Secret\n\nnope", encoding="utf-8")
    assert json.loads(fetch_paper("../secret")) == {}
    assert json.loads(fetch_paper("/etc/hosts")) == {}


def test_fetch_without_a_corpus_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(module.CORPUS_ENV_VAR, raising=False)
    assert json.loads(fetch_paper("anything")) == {}


def test_a_body_on_one_long_line_still_yields_several_passages(
    corpus: Path,
) -> None:
    """Search must return passages even when the paper has no line breaks.

    This scorer is a second implementation of the viewer's, and it drifted:
    the viewer split oversized paragraphs and this did not, so a paper whose
    body is one long line came back as a single passage covering all of it.
    """
    results = json.loads(search_paper_corpus("trametinib MEK", 10))
    assert len(results) > 1
    longest = max(len(v["abstract"]) for v in results.values())
    assert longest <= module._TARGET_CHUNK_CHARS * 2
