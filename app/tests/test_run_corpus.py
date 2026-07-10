"""Tests for the private run-corpus keyword retriever (Milestone 7)."""

from __future__ import annotations

from app.run_corpus import (
    CorpusDocument,
    KeywordCorpusRetriever,
)


def _corpus() -> list[CorpusDocument]:
    return [
        CorpusDocument(
            "d1",
            "Kinase X in AML",
            "Kinase X inhibition reduces tumor growth in acute myeloid "
            "leukemia cells through apoptosis.",
        ),
        CorpusDocument(
            "d2",
            "Photosynthesis",
            "Chloroplast electron transport drives carbon fixation in plants.",
        ),
        CorpusDocument(
            "d3",
            "Immune surveillance",
            "Receptor Y blockade restores immune surveillance against tumors.",
        ),
    ]


def test_retrieves_topically_relevant_document() -> None:
    """A query retrieves the on-topic document above off-topic ones."""
    retriever = KeywordCorpusRetriever(_corpus())
    hits = retriever.retrieve("kinase inhibition tumor growth AML", k=2)
    assert hits
    assert hits[0].document.doc_id == "d1"
    assert hits[0].score > 0.0


def test_off_topic_query_returns_no_spurious_hits() -> None:
    """A query with no shared terms returns nothing (not a random doc)."""
    retriever = KeywordCorpusRetriever(_corpus())
    assert retriever.retrieve("quantum chromodynamics gluon") == []


def test_retrieval_is_deterministic() -> None:
    """The same query returns the same ordered hits every time."""
    retriever = KeywordCorpusRetriever(_corpus())
    first = [h.document.doc_id for h in retriever.retrieve("tumor immune", k=3)]
    second = [
        h.document.doc_id for h in retriever.retrieve("tumor immune", k=3)
    ]
    assert first == second


def test_empty_corpus_returns_nothing() -> None:
    """Retrieval over an empty corpus is safe and empty."""
    assert KeywordCorpusRetriever([]).retrieve("anything") == []
