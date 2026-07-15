"""Tests for claim-level grounding, entailment, and publication gating (M5).

Proves the M5 invariants: an unsupported citation cannot become "verified"
through word overlap (INSUFFICIENT, not SUPPORTS on weak overlap), contradiction
dominates and triggers the gate, resolvability is judged apart from support, and
revisions are re-assessable. Also proves the P0.5 additions: claim-specific
retrieval, provenance-stamped support spans with exact offsets, a swappable
assessor, and the anti-hallucination guard that downgrades a verdict whose cited
quote is not present in the evidence.
"""

from __future__ import annotations

from app.claims import (
    AssessorDraft,
    CitationMetadata,
    EntailmentLabel,
    EvidencePassage,
    GateDecision,
    Resolvability,
    as_passages,
    assess_claim,
    assess_resolvability,
    extract_atomic_claims,
    locate_span,
    publication_gate,
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


# --- Entailment: lexical overlap is not "verified" --------------------------


def test_weak_overlap_is_insufficient_not_supported() -> None:
    """A passage merely sharing a couple of words does not SUPPORT the claim."""
    claim = "Inhibiting kinase X reduces tumor growth in AML cells."
    passages = as_passages(
        ["This unrelated review discusses cardiac tissue growth."]
    )
    result = assess_claim(claim, passages)
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.supporting_passages == ()


def test_strong_topical_overlap_supports_with_located_span() -> None:
    """A restating passage SUPPORTS, and the span points at the source."""
    claim = "Inhibiting kinase X reduces tumor growth in AML cells."
    passage = EvidencePassage(
        evidence_id="ev-1",
        text="Kinase X inhibition reduces tumor growth across several AML "
        "cells.",
        source="pubmed",
        url="https://example.org/1",
    )
    result = assess_claim(claim, [passage])
    assert result.label is EntailmentLabel.SUPPORTS
    assert len(result.supporting_passages) == 1
    span = result.supporting_passages[0]
    assert span.evidence_id == "ev-1"
    assert span.url == "https://example.org/1"
    # The offsets index into the exact passage text.
    assert passage.text[span.start : span.end] == span.quote
    assert "kinase x inhibition" in span.quote.lower()
    assert result.assessor  # provenance recorded


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


# --- Publication gate -------------------------------------------------------


def test_gate_blocks_contradicted_hypothesis() -> None:
    """A contradicted fundamental claim blocks publication."""
    assessments = [
        assess_claim(
            "Kinase X inhibition reduces AML tumor growth.",
            as_passages(
                ["Kinase X inhibition did not reduce AML tumor growth."]
            ),
        )
    ]
    result = publication_gate(assessments)
    assert result.decision is GateDecision.BLOCK
    assert result.contradicted_claims
    # The rank-and-publish config (the pre-ranking call site) loosens support
    # requirements but must still withhold a contradicted idea: contradiction
    # is a hard block independent of allow_speculative/require_supported_claim.
    loosened = publication_gate(
        assessments, allow_speculative=True, require_supported_claim=False
    )
    assert loosened.decision is GateDecision.BLOCK


def test_gate_blocks_unsupported_unless_speculative_allowed() -> None:
    """Unsupported claims block by default but pass as labeled speculation."""
    assessments = [
        assess_claim(
            "Kinase X inhibition reduces AML tumor growth.",
            as_passages(
                ["An unrelated passage about photosynthesis in plants."]
            ),
        )
    ]
    assert publication_gate(assessments).decision is GateDecision.BLOCK
    allowed = publication_gate(assessments, allow_speculative=True)
    assert allowed.decision is GateDecision.ALLOW
    assert allowed.unsupported_claims  # surfaced as speculative
    assert allowed.speculative_claims == allowed.unsupported_claims


def test_gate_allows_only_explicitly_speculative_insufficient_claims() -> None:
    """A proposed mechanism can remain open while background stays strict."""
    proposed = assess_claim(
        "We hypothesize kinase X may alter neuronal recovery.",
        as_passages(["An unrelated passage about photosynthesis."]),
    )
    categorical = assess_claim(
        "Kinase X is established as the neuronal recovery controller.",
        as_passages(["An unrelated passage about photosynthesis."]),
    )

    blocked = publication_gate(
        [proposed, categorical],
        explicitly_speculative_claims={proposed.claim},
    )
    assert blocked.decision is GateDecision.BLOCK
    assert blocked.speculative_claims == (proposed.claim,)

    allowed = publication_gate(
        [proposed], explicitly_speculative_claims={proposed.claim}
    )
    assert allowed.decision is GateDecision.ALLOW
    assert allowed.speculative_claims == (proposed.claim,)

    ungrounded = publication_gate(
        [proposed],
        explicitly_speculative_claims={proposed.claim},
        require_supported_claim=True,
    )
    assert ungrounded.decision is GateDecision.BLOCK
    assert ungrounded.reason == "no evidence-supported contextual claim"


def test_gate_allows_supported_hypothesis() -> None:
    """A hypothesis whose claims are supported publishes."""
    assessments = [
        assess_claim(
            "Kinase X inhibition reduces AML tumor growth.",
            as_passages(
                ["Kinase X inhibition reduces AML tumor growth in cell lines."]
            ),
        )
    ]
    result = publication_gate(assessments)
    assert result.decision is GateDecision.ALLOW


def test_gate_blocks_hypothesis_with_no_claims() -> None:
    """A hypothesis with no assessable claims cannot publish."""
    assert publication_gate([]).decision is GateDecision.BLOCK


def test_revision_is_reassessed() -> None:
    """Re-assessing a revised claim against new evidence updates the verdict."""
    claim = "Kinase X inhibition reduces AML tumor growth."
    contradicted = assess_claim(
        claim,
        as_passages(["Kinase X inhibition did not reduce AML tumor growth."]),
    )
    assert contradicted.label is EntailmentLabel.CONTRADICTS

    revised = "Combined kinase X and cofactor W inhibition reduces AML growth."
    supported = assess_claim(
        revised,
        as_passages(
            [
                "Combined kinase X and cofactor W inhibition reduces AML "
                "growth durably in patient-derived cells."
            ]
        ),
    )
    assert supported.label is EntailmentLabel.SUPPORTS
