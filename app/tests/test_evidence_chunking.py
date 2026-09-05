"""Tests for chunking long evidence into passage-sized units.

Regression coverage for the incident this module exists to close: a
production run (44e848fb) fed each claim-verification call whole articles
-- title + abstract + up to 200k chars of full text -- as a single
"passage". ~600 gate calls averaged 34-46k prompt tokens for ~250 tokens of
answer (28M of the run's 29M total tokens), with a 6.9% cache hit rate
because the claim (which changes every call) preceded the evidence (which
recurs across calls), so the recurring papers never formed a stable
prefix.
"""

from __future__ import annotations

from app.evidence_chunking import (
    CHUNK_MAX_CHARS,
    CHUNK_OVERLAP_CHARS,
    chunk_evidence_passage,
    parent_evidence_id,
)


def test_long_body_yields_multiple_chunks_under_the_size_limit() -> None:
    """A 40k-char article body is split into several bounded chunks."""
    paragraph = "Kinase X inhibition reduces tumor growth. " * 40
    body = "\n\n".join([paragraph] * 25)  # ~43k chars
    assert len(body) > 40_000

    passages = chunk_evidence_passage(
        "art-1",
        head_text="Title. Abstract sentence.",
        body_text=body,
        source="pubmed",
        url="https://example.org/1",
    )

    assert len(passages) > 1
    # A chunk's true ceiling includes the overlap prefix plus the joining
    # space between it and the chunk's own text (see CHUNK_OVERLAP_CHARS).
    bound = CHUNK_MAX_CHARS + CHUNK_OVERLAP_CHARS + 1
    for passage in passages:
        assert len(passage.text) <= bound


def test_chunks_carry_provenance_back_to_the_parent_article() -> None:
    """Every chunk's evidence_id resolves back to the parent article id."""
    body = ("Alpha sentence one. Beta sentence two.\n\n") * 200
    passages = chunk_evidence_passage(
        "pmid-42",
        head_text="Title only.",
        body_text=body,
        source="pubmed",
        url="https://example.org/42",
    )

    assert len(passages) > 1
    for passage in passages:
        assert passage.evidence_id.startswith("pmid-42#")
        assert parent_evidence_id(passage.evidence_id) == "pmid-42"


def test_abstract_only_article_is_unchanged() -> None:
    """No body text -> exactly one passage under the article's bare id."""
    passages = chunk_evidence_passage(
        "pmid-7",
        head_text="Title. A short abstract about kinase inhibition.",
        body_text="",
        source="pubmed",
        url="https://example.org/7",
    )

    assert len(passages) == 1
    assert passages[0].evidence_id == "pmid-7"
    assert (
        passages[0].text == "Title. A short abstract about kinase inhibition."
    )


def test_parent_evidence_id_is_a_no_op_on_an_unchunked_id() -> None:
    """A bare article/evidence id (no chunk suffix) passes through unchanged."""
    assert parent_evidence_id("pmid-7") == "pmid-7"
    assert parent_evidence_id("private-document-with-a-hash#tag") == (
        "private-document-with-a-hash#tag"
    )


def test_a_deep_supporting_sentence_survives_chunking() -> None:
    """A sentence buried deep in a long article still lands in some chunk."""
    filler = "Unrelated background discussion sentence number filler. "
    needle = "Kinase X inhibition reduces tumor growth in AML cell lines."
    body = (filler * 400) + needle + (" " + filler * 400)

    passages = chunk_evidence_passage(
        "art-deep",
        head_text="Title.",
        body_text=body,
        source="pubmed",
        url="https://example.org/deep",
    )

    assert any(needle in passage.text for passage in passages)
