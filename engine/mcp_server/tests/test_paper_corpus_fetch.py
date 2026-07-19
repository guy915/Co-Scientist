"""Tests for the local paper-corpus fetch tool.

Each test builds its own corpus in a temp directory rather than reading the
committed one, so behaviour is pinned to fixed inputs. The group's papers are
no longer searched here -- the app injects the catalog and the model fetches a
paper in full by paper_id -- so only fetch_paper remains.
"""

import json
from pathlib import Path

import pytest
from mcp_server.tools.lit_review import search_paper_corpus as module
from mcp_server.tools.lit_review.search_paper_corpus import fetch_paper


@pytest.fixture()
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "mapk.md").write_text(
        "# MAPK Feedback Paper\n\n"
        "Trametinib inhibits MEK and relieves ERK negative feedback.",
        encoding="utf-8",
    )
    monkeypatch.setenv(module.CORPUS_ENV_VAR, str(root))
    return root


def test_fetch_reads_the_whole_paper(corpus: Path) -> None:
    """fetch_paper returns the paper's title and complete text by paper_id."""
    full = json.loads(fetch_paper("mapk"))
    body = next(iter(full.values()))
    assert body["title"] == "MAPK Feedback Paper"
    assert "Trametinib inhibits MEK" in body["content"]
    assert body["source_id"] == "mapk"


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
    """No corpus is the default state; the agent should fall back to PubMed."""
    monkeypatch.delenv(module.CORPUS_ENV_VAR, raising=False)
    assert json.loads(fetch_paper("anything")) == {}
