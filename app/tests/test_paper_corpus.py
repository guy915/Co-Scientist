"""Tests for paper-corpus sanitation, chunking, and retrieval.

Every test builds its own corpus in a temp directory. The real corpus is
publisher-copyrighted and git-ignored, so nothing here may assume it exists.
"""

from __future__ import annotations

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


def test_chunking_splits_a_paper_into_attributed_passages() -> None:
    text = " ".join(f"Sentence number {i} about kinases." for i in range(400))
    chunks = paper_corpus.chunk_paper("paper-1", "A Title", text)
    assert len(chunks) > 1
    # Every passage names its paper, so a hit is attributable on its own.
    assert all(c.title == "A Title" for c in chunks)
    assert all(c.doc_id.startswith("paper-1#") for c in chunks)
    # Ids are unique and ordered.
    assert len({c.doc_id for c in chunks}) == len(chunks)


def test_chunking_bounds_a_single_huge_paragraph() -> None:
    """A flattened table arrives as one enormous line, and must still split.

    Otherwise one passage crowds out every other in the prompt it lands in.
    """
    text = " ".join(f"Value {i} was recorded." for i in range(2000))
    chunks = paper_corpus.chunk_paper("wide", "Wide Table", text)
    budget = paper_corpus.TARGET_CHUNK_TOKENS * 4
    assert len(chunks) > 1
    assert max(len(c.text) for c in chunks) <= budget * 2


def _install(tmp_path: Path) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "mapk.md").write_text(
        "# MAPK Feedback Paper\n\n"
        + "Trametinib inhibits MEK and relieves ERK negative feedback. " * 40,
        encoding="utf-8",
    )
    (corpus / "stat3.md").write_text(
        "# STAT3 Paper\n\n"
        + "STAT3 phosphorylation at Y705 drives survivin expression. " * 40,
        encoding="utf-8",
    )
    return corpus


def test_retrieval_finds_the_relevant_paper(tmp_path: Path) -> None:
    retriever = paper_corpus.build_retriever(_install(tmp_path))
    assert retriever is not None
    hits = retriever.retrieve("trametinib MEK feedback", k=3)
    assert hits
    assert hits[0].document.title == "MAPK Feedback Paper"


def test_absent_corpus_is_not_an_error(tmp_path: Path) -> None:
    """A fresh checkout has no corpus; that is normal, not a failure."""
    assert paper_corpus.load_corpus(tmp_path / "nothing") == []
    assert paper_corpus.build_retriever(tmp_path / "nothing") is None


@pytest.fixture()
def installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    monkeypatch.setenv(paper_corpus.CORPUS_ENV_VAR, str(_install(tmp_path)))
    paper_corpus.reset_cache()
    yield
    paper_corpus.reset_cache()


def test_retrieve_for_is_gated_to_the_owning_audience(installed: None) -> None:
    """The corpus is one lab's library, not a general resource."""
    assert paper_corpus.retrieve_for("sbi_ucd", "trametinib MEK", k=3)
    for other in ("google", "general", None):
        assert paper_corpus.retrieve_for(other, "trametinib MEK", k=3) == []


def test_retrieve_for_handles_an_empty_query(installed: None) -> None:
    assert paper_corpus.retrieve_for("sbi_ucd", "   ", k=3) == []


def test_format_passages_attributes_every_passage(installed: None) -> None:
    hits = paper_corpus.retrieve_for("sbi_ucd", "STAT3 survivin", k=2)
    rendered = paper_corpus.format_passages(hits)
    assert "STAT3 Paper" in rendered
    assert paper_corpus.format_passages([]) == ""
