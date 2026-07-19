"""Tests for paper-corpus sanitation, chunking, and retrieval.

Every test builds its own corpus in a temp directory rather than reading the
committed one, so behaviour is pinned to fixed inputs and does not shift when
a paper is re-ingested.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import paper_corpus

# A miniature paper carrying each artefact sanitation is meant to remove.
_RAW = """Downloaded from example.org
A Study of Kinase Signalling

We show that MEK inhibition relieves feedback and activates PI3K, which
drives adaptive resis-
tance in the tumour cells we examined.

ST
V
Hyperplane

Downloaded from example.org
The effect persisted across every cell line tested in this work.

Downloaded from example.org
Downloaded from example.org
References
1. Smolen, P., Baxter, D. A. (1998) Am. J. Physiol. 274, C531.
2. Kholodenko, B. N. (1999) J. Biol. Chem. 274, 30169.
"""


def test_sanitize_removes_back_matter_and_debris() -> None:
    body, report = paper_corpus.sanitize(_RAW)
    # The reference list goes, along with the heading that introduced it.
    assert "Smolen" not in body
    assert "References" not in body
    # Page furniture repeated once per page goes.
    assert "Downloaded from" not in body
    # Figure glyphs split one per line go.
    assert "\nST\n" not in body and "\nV\n" not in body
    # The prose stays.
    assert "MEK inhibition relieves feedback" in body
    assert "persisted across every cell line" in body
    assert 0.0 < report.kept_fraction < 1.0


def test_sanitize_rejoins_words_split_across_lines() -> None:
    """A typeset line break must not leave "resis" and "tance" as tokens."""
    body, _ = paper_corpus.sanitize(_RAW)
    assert "resistance" in body
    assert "resis-" not in body


def test_sanitize_cuts_an_unheaded_bibliography() -> None:
    """PNAS prints no heading -- the numbered list is the only signal.

    The first entries also wrap onto continuation lines, which is what makes
    a naive density check cut too late and leak the opening references.
    """
    raw = "\n".join(
        ["Our conclusion is that the network rewires under inhibition."]
        + [
            f"{i}. Author, A. B. & Other, C. D. (19{70 + i}) J. Biol. Chem."
            + ("\n   274, 30169-30181." if i <= 3 else "")
            for i in range(1, 12)
        ]
    )
    body, _ = paper_corpus.sanitize(raw)
    assert "Our conclusion" in body
    # Including the very first entry, the one a late cut would leave behind.
    assert "Author, A. B." not in body
    assert "30169" not in body


def test_sanitize_keeps_numbered_prose_without_years() -> None:
    """Numbered method steps look like citations but must survive.

    The year requirement is what separates them, so this pins it.
    """
    raw = "\n".join(
        f"{i}. Incubate the sample and record the phospho-ERK readout."
        for i in range(1, 12)
    )
    body, _ = paper_corpus.sanitize(raw)
    assert "Incubate the sample" in body


def test_default_corpus_directory_is_inside_the_repository() -> None:
    """The default path is load-bearing now that the corpus is committed.

    It resolved one level too high for a while and nothing caught it: every
    other test sets the environment override, and an absent corpus is a
    supported state, so the wrong path failed silently as "no corpus".
    """
    default = paper_corpus._DEFAULT_CORPUS_DIR
    assert default.name == "sbi_ucd"
    # app/app/paper_corpus.py -> app/app -> app -> the repository root, which
    # is the directory holding both `app` and `corpus`.
    assert (default.parent.parent / "app").is_dir()


def _install(tmp_path: Path) -> Path:
    """Write a two-paper corpus with a catalog into a temp directory."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "mapk.md").write_text(
        "# MAPK Feedback Paper\n\nTrametinib inhibits MEK.", encoding="utf-8"
    )
    (corpus / "stat3.md").write_text(
        "# STAT3 Paper\n\nSTAT3 drives survivin.", encoding="utf-8"
    )
    (corpus / paper_corpus.CATALOG_FILENAME).write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "paper_id": "mapk",
                        "title": "MAPK Feedback Paper",
                        "abstract": "Trametinib relieves ERK feedback.",
                    },
                    {
                        "paper_id": "stat3",
                        "title": "STAT3 Paper",
                        "abstract": "STAT3 at Y705 drives survivin.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return corpus


@pytest.fixture()
def installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    monkeypatch.setenv(paper_corpus.CORPUS_ENV_VAR, str(_install(tmp_path)))
    paper_corpus.load_catalog.cache_clear()
    yield
    paper_corpus.load_catalog.cache_clear()


def test_absent_catalog_is_not_an_error(tmp_path: Path) -> None:
    """A fresh checkout has no corpus; that is normal, not a failure."""
    assert paper_corpus.load_catalog(tmp_path / "nothing") == ()


def test_catalog_loads_every_paper(installed: None) -> None:
    papers = paper_corpus.load_catalog()
    assert [p.paper_id for p in papers] == ["mapk", "stat3"]
    assert papers[0].title == "MAPK Feedback Paper"
    assert "Trametinib" in papers[0].abstract


def test_committed_catalog_matches_the_committed_papers() -> None:
    """Every catalog entry names a paper that is actually on disk to fetch.

    A catalog entry whose paper_id has no file would advertise a fetch that
    returns nothing, so this pins the two in step.
    """
    papers = paper_corpus.load_catalog()
    assert len(papers) >= 15, "the committed corpus catalog should load"
    corpus = paper_corpus.corpus_dir()
    for paper in papers:
        assert (corpus / f"{paper.paper_id}.md").is_file(), paper.paper_id
        assert paper.title and paper.abstract


def test_format_catalog_prints_ids_and_the_fetch_instruction(
    installed: None,
) -> None:
    """The catalog is now the only place paper_ids are advertised."""
    rendered = paper_corpus.format_catalog(paper_corpus.load_catalog())
    assert "MAPK Feedback Paper" in rendered
    assert "paper_id: `mapk`" in rendered
    assert "fetch_paper" in rendered
    assert paper_corpus.format_catalog(()) == ""


def test_catalog_context_is_gated_to_the_owning_audience(
    installed: None,
) -> None:
    """The corpus is one lab's library, not a general resource."""
    assert paper_corpus.catalog_context("sbi_ucd")
    for other in ("google", "general", None):
        assert paper_corpus.catalog_context(other) == ""


def test_catalog_context_honours_the_toggle_but_audience_dominates(
    installed: None,
) -> None:
    """The toggle can opt an SBI run out; it cannot opt another audience in."""
    assert paper_corpus.catalog_context("sbi_ucd", enabled=True)
    assert paper_corpus.catalog_context("sbi_ucd", enabled=False) == ""
    # A forged toggle on a non-corpus audience still yields nothing.
    assert paper_corpus.catalog_context("general", enabled=True) == ""


def test_fetch_tool_is_withheld_from_other_audiences() -> None:
    """The agent's own route to the corpus is gated like the catalog.

    An agent can call `fetch_paper` itself while drafting, validating, and
    reflecting, so it is withheld per-run for every audience but the corpus
    owner -- and for the owner too when the connector is off -- otherwise a
    non-SBI run could read the lab's library directly.
    """
    assert paper_corpus.disabled_tools_for("sbi_ucd") == []
    assert paper_corpus.disabled_tools_for("sbi_ucd", enabled=False) == [
        "paper_corpus_fetch"
    ]
    for other in ("google", "general", "", None):
        assert paper_corpus.disabled_tools_for(other) == [
            "paper_corpus_fetch"
        ]
