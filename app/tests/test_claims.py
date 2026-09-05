"""Tests for claim extraction, entailment, and provenance (M5).

Proves the M5 invariants: an unsupported citation cannot become "verified"
through word overlap (INSUFFICIENT, not SUPPORTS on weak overlap),
contradiction dominates other verdicts, and resolvability is judged apart
from support. Also proves the P0.5 additions: claim-specific retrieval,
provenance-stamped support spans with exact offsets, a swappable assessor,
and the anti-hallucination guard that downgrades a verdict whose cited quote
is not present in the evidence.

What the *gate* then does with these verdicts is ``test_claims_gate.py``,
split off when this file passed the module-size budget.
"""

from __future__ import annotations

from app.claims import (
    AssessorDraft,
    CitationMetadata,
    EntailmentLabel,
    EvidencePassage,
    Resolvability,
    as_passages,
    assess_claim,
    assess_resolvability,
    extract_atomic_claims,
    locate_span,
    retrieve_passages,
)

# --- Atomic claim extraction ------------------------------------------------


def test_extracts_atomic_claims_and_drops_fragments() -> None:
    """Sentences become claims; short fragments and duplicates are dropped."""
    text = (
        "Inhibiting kinase X reduces tumor growth in AML cells. "
        "Ok. "  # too short -> dropped
        "The mechanism involves downstream apoptosis signaling. "
        "Inhibiting kinase X reduces tumor growth in AML cells."  # duplicate
    )
    claims = extract_atomic_claims(text)
    assert claims == [
        "Inhibiting kinase X reduces tumor growth in AML cells.",
        "The mechanism involves downstream apoptosis signaling.",
    ]


def test_extraction_drops_sentences_asserting_an_evidence_gap() -> None:
    """Novelty statements about the corpus are not empirical claims.

    A sentence asserting that prior work is absent is a negative existential
    over the very corpus the assessor entails against: no passage can confirm
    it, and any topical passage reads as contradicting it. Every example here
    is verbatim from a run whose ideas were withheld on exactly one such
    sentence apiece.
    """
    text = (
        "Menin inhibition destabilizes c-Myc in KMT2A-rearranged AML. "
        "Within the retrieved literature, no source tests whether PI3K "
        "inhibition alone reactivates the composite program. "
        "This interaction appears unexplored in the retrieved literature. "
        "This hypothesis is formulated without access to a literature "
        "review; no citation keys are available. "
        "The apoptotic mechanism is not systematically characterized. "
        "Dual blockade has not been tested in this subtype."
    )
    assert extract_atomic_claims(text) == [
        "Menin inhibition destabilizes c-Myc in KMT2A-rearranged AML."
    ]


# A full-length title+abstract -- the shape an EvidencePassage carries in a run
# (claim_grounding.evidence_passages joins an evidence row's title and
# abstract). The length is the point: a one-sentence claim against a passage
# many times its size is the asymmetry a union-denominated metric caps, and at
# claim size Jaccard and coverage agree, so no assertion below could tell a
# capped metric from a working one. It restates the claim in other words --
# never saying "inhibit" -- so it is a paraphrase, not a copy.
_SUPPORTING_ABSTRACT = (
    "Selective kinase X blockade in acute myeloid leukemia: preclinical "
    "evidence across patient-derived models. "
    "Acute myeloid leukemia remains difficult to treat, and the contribution "
    "of kinase X to disease maintenance has not been established in primary "
    "material. We profiled expression across sixty-one primary specimens and "
    "eleven established lines, then applied a selective small-molecule "
    "antagonist alongside cytarabine and an isotype-matched vehicle control. "
    "Target engagement was verified by phosphoproteomic readout at three "
    "separate residues. Blocking the kinase curtailed tumor "
    "proliferation in every AML model tested, with cell-cycle arrest at the "
    "G1 checkpoint and induction of apoptosis in treated cells within "
    "forty-eight hours. Colony formation from healthy donor progenitors was "
    "unaffected at equivalent concentrations, suggesting a usable "
    "therapeutic window. Transcriptional profiling implicated downstream "
    "signaling through the canonical survival axis rather than off-target "
    "activity. These results support further evaluation of this strategy in "
    "acute myeloid leukemia."
)

_KINASE_CLAIM = "Inhibiting kinase X reduces tumor growth in AML cells."


# --- Entailment: lexical overlap is not "verified" --------------------------


def test_weak_overlap_is_insufficient_not_supported() -> None:
    """A passage merely sharing a couple of words does not SUPPORT the claim."""
    passages = as_passages(
        ["This unrelated review discusses cardiac tissue growth."]
    )
    result = assess_claim(_KINASE_CLAIM, passages)
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.supporting_passages == ()


def test_strong_topical_overlap_supports_with_located_span() -> None:
    """A restating full-length abstract SUPPORTS; the span cites the source."""
    passage = EvidencePassage(
        evidence_id="ev-1",
        text=_SUPPORTING_ABSTRACT,
        source="pubmed",
        url="https://example.org/1",
    )
    # Guard the fixture, not just the verdict: shrink this passage back to the
    # size of the claim and the assertion below passes under a union-
    # denominated metric too, which is how the cap survived here once already.
    assert len(passage.text.split()) > 8 * len(_KINASE_CLAIM.split())

    result = assess_claim(_KINASE_CLAIM, [passage])
    assert result.label is EntailmentLabel.SUPPORTS
    assert len(result.supporting_passages) == 1
    span = result.supporting_passages[0]
    assert span.evidence_id == "ev-1"
    assert span.url == "https://example.org/1"
    # The offsets index into the exact passage text.
    assert passage.text[span.start : span.end] == span.quote
    assert "curtailed tumor proliferation" in span.quote.lower()
    assert result.assessor  # provenance recorded


def test_passage_quoting_the_claim_verbatim_reaches_the_top_band() -> None:
    """A source literally containing the claim must reach SUPPORTS.

    The sanity check ``citations._token_overlap`` prescribes for any new
    similarity threshold: feed it a document containing the claim word for
    word. If that cannot reach the top state the threshold is unreachable and
    every real citation collapses into the bottom one -- which is what a
    union-denominated score does here, scoring 0.071 and missing even partial.
    """
    passage = EvidencePassage(
        evidence_id="ev-1",
        text=_SUPPORTING_ABSTRACT.replace(
            "These results support",
            f"{_KINASE_CLAIM} These results support",
        ),
        source="pubmed",
        url="https://example.org/1",
    )
    result = assess_claim(_KINASE_CLAIM, [passage])
    assert result.label is EntailmentLabel.SUPPORTS
    span = result.supporting_passages[0]
    # The located span is the claim sentence itself, verbatim from the source.
    assert span.quote == _KINASE_CLAIM
    assert passage.text[span.start : span.end] == span.quote


def test_contradiction_dominates_over_support() -> None:
    """A contradicting passage yields CONTRADICTS even amid supporting text."""
    claim = "Inhibiting kinase X reduces tumor growth in AML cells."
    passages = as_passages(
        [
            "Kinase X inhibition reduces tumor growth in AML cells.",
            "Kinase X inhibition did not reduce tumor growth in AML cells.",
        ]
    )
    result = assess_claim(claim, passages)
    assert result.label is EntailmentLabel.CONTRADICTS
    assert result.contradicting_passages
    assert result.is_fundamental_failure


def test_midband_overlap_is_partial_support_with_located_span() -> None:
    """A near-miss passage (on-topic, not entailing) is PARTIAL, not INSUFF.

    Its span is still cited as supporting evidence, so a reader can open the
    exact passage behind the partial verdict and the badge can credit it.
    """
    claim = "Inhibiting kinase X reduces tumor growth in AML cells."
    passage = EvidencePassage(
        evidence_id="ev-1",
        text="Kinase enzymes regulate cellular growth under diverse "
        "metabolic conditions across many organisms.",
        source="pubmed",
        url="https://example.org/1",
    )
    result = assess_claim(claim, [passage])
    assert result.label is EntailmentLabel.PARTIAL
    assert len(result.supporting_passages) == 1
    span = result.supporting_passages[0]
    assert passage.text[span.start : span.end] == span.quote


def test_full_support_beats_a_partial_near_miss() -> None:
    """A fully-entailing passage wins SUPPORTS even alongside a partial one."""
    claim = "Inhibiting kinase X reduces tumor growth in AML cells."
    passages = as_passages(
        [
            "Kinase enzymes regulate cellular growth under diverse "
            "metabolic conditions across many organisms.",
            "Kinase X inhibition reduces tumor growth across several AML "
            "cells.",
        ]
    )
    result = assess_claim(claim, passages)
    assert result.label is EntailmentLabel.SUPPORTS


def test_partial_without_locatable_span_downgraded() -> None:
    """A PARTIAL verdict whose cited quote is absent becomes INSUFFICIENT."""

    def _fabricating_assessor(
        claim: str, passages: list[EvidencePassage]
    ) -> AssessorDraft:
        return AssessorDraft(
            label=EntailmentLabel.PARTIAL,
            supporting=(("ev-1", "a quote that is nowhere in the passage"),),
        )

    result = assess_claim(
        "Kinase X inhibition reduces tumor growth.",
        [EvidencePassage(evidence_id="ev-1", text="Unrelated passage text.")],
        assessor=_fabricating_assessor,  # type: ignore[arg-type]
    )
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.supporting_passages == ()


# --- Claim-specific retrieval -----------------------------------------------


def test_retrieval_ranks_relevant_passages_and_drops_unrelated() -> None:
    """Retrieval returns the most relevant; zero-overlap are dropped."""
    claim = "Kinase X inhibition reduces AML tumor growth."
    passages = as_passages(
        [
            "A completely unrelated study of ocean salinity gradients.",
            "Kinase X inhibition reduces AML tumor growth in cell lines.",
            "Tumor growth kinase inhibition AML reduction discussed here.",
        ]
    )
    ranked = retrieve_passages(claim, passages, top_k=2)
    assert len(ranked) == 2
    # The unrelated salinity passage is dropped entirely (zero overlap).
    assert all("salinity" not in p.text for p in ranked)


def test_retrieval_bounds_the_assessed_pool() -> None:
    """Only the top_k retrieved passages reach the assessor."""
    seen: list[int] = []

    def _counting_assessor(
        claim: str, passages: list[EvidencePassage]
    ) -> AssessorDraft:
        seen.append(len(passages))
        return AssessorDraft(label=EntailmentLabel.INSUFFICIENT)

    passages = as_passages(
        [f"kinase inhibition tumor growth variant {i}" for i in range(10)]
    )
    assess_claim(
        "kinase inhibition reduces tumor growth",
        passages,
        assessor=_counting_assessor,  # type: ignore[arg-type]
        top_k=3,
    )
    assert seen == [3]


def test_deep_supporting_sentence_in_a_chunked_article_is_located() -> None:
    """Evidence buried deep in a long, chunked article is still located.

    Regression for whole-article-as-passage grounding: chunking must not
    cost retrieval its ability to find and cite text far from an article's
    start, and the located span must still map back to the parent article.
    """
    from app.evidence_chunking import chunk_evidence_passage, parent_evidence_id

    filler = "Unrelated background discussion sentence about other topics. "
    needle = "Kinase X inhibition reduces tumor growth in AML cell lines."
    body = (filler * 300) + needle + (" " + filler * 300)
    chunks = chunk_evidence_passage(
        "article-99",
        head_text="Title only, no abstract.",
        body_text=body,
        source="pubmed",
        url="https://example.org/99",
    )
    assert len(chunks) > 1  # the chunking actually happened

    claim = "Kinase X inhibition reduces tumor growth in AML cell lines."
    result = assess_claim(claim, chunks, top_k=3)
    assert result.label is EntailmentLabel.SUPPORTS
    span = result.supporting_passages[0]
    assert needle in span.quote or span.quote in needle
    assert parent_evidence_id(span.evidence_id) == "article-99"


# --- Provenance / span location ---------------------------------------------


def test_locate_span_is_whitespace_and_case_tolerant() -> None:
    """A quote with altered whitespace/casing still locates an exact span."""
    passage = EvidencePassage(
        evidence_id="ev-1",
        text="Kinase X   inhibition reduces tumor growth markedly.",
    )
    span = locate_span(passage, "kinase x inhibition REDUCES tumor growth")
    assert span is not None
    # Offsets index into the original (multi-space) text verbatim.
    assert passage.text[span.start : span.end] == span.quote
    assert span.quote.startswith("Kinase X")


def test_locate_span_returns_none_for_absent_quote() -> None:
    """A quote not present in the passage cannot be located."""
    passage = EvidencePassage(evidence_id="ev-1", text="Some evidence text.")
    assert locate_span(passage, "a quote that does not appear") is None


def test_hallucinated_support_quote_is_downgraded_to_insufficient() -> None:
    """A SUPPORTS verdict whose quote is absent from the passage is unproven."""

    def _hallucinating_assessor(
        claim: str, passages: list[EvidencePassage]
    ) -> AssessorDraft:
        # Cites a quote that does not appear in the passage.
        return AssessorDraft(
            label=EntailmentLabel.SUPPORTS,
            supporting=(("ev-1", "text that is not in the evidence"),),
        )

    passages = [
        EvidencePassage(evidence_id="ev-1", text="Real evidence about kinases.")
    ]
    result = assess_claim(
        "kinase claim",
        passages,
        assessor=_hallucinating_assessor,  # type: ignore[arg-type]
    )
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.supporting_passages == ()


def test_supported_verdict_keeps_located_span_from_swappable_assessor() -> None:
    """A swappable assessor citing a real quote yields a located span."""

    def _quote_assessor(
        claim: str, passages: list[EvidencePassage]
    ) -> AssessorDraft:
        return AssessorDraft(
            label=EntailmentLabel.SUPPORTS,
            supporting=(("ev-1", "reduces tumor growth"),),
        )

    passage = EvidencePassage(
        evidence_id="ev-1",
        text="Kinase X inhibition reduces tumor growth in AML.",
        url="https://example.org/1",
    )
    result = assess_claim(
        "kinase claim",
        [passage],
        assessor=_quote_assessor,  # type: ignore[arg-type]
        assessor_id="llm:test",
    )
    assert result.label is EntailmentLabel.SUPPORTS
    assert result.assessor == "llm:test"
    span = result.supporting_passages[0]
    assert (
        passage.text[span.start : span.end]
        == span.quote
        == "reduces tumor growth"
    )


# --- Resolvability separate from support ------------------------------------


def test_resolvability_is_independent_of_support() -> None:
    """Retraction/reachability is judged apart from claim support."""
    assert (
        assess_resolvability(CitationMetadata(url="http://x", retracted=True))
        is Resolvability.RETRACTED
    )
    assert (
        assess_resolvability(CitationMetadata(url="", available=True))
        is Resolvability.UNRESOLVABLE
    )
    assert (
        assess_resolvability(CitationMetadata(url="http://x", available=True))
        is Resolvability.RESOLVABLE
    )


def test_resolvability_uses_swappable_resolver() -> None:
    """A live resolver can be injected in place of the offline default."""

    def _live_resolver(meta: CitationMetadata) -> Resolvability:
        # Pretend a lookup found the DOI retracted despite a reachable URL.
        return Resolvability.RETRACTED

    verdict = assess_resolvability(
        CitationMetadata(url="http://x", doi="10.1/abc", available=True),
        resolver=_live_resolver,
    )
    assert verdict is Resolvability.RETRACTED
