"""Tests for claim-level grounding, entailment, and publication gating (M5).

Proves the M5 invariants: an unsupported citation cannot become "verified"
through word overlap (INSUFFICIENT, not SUPPORTS on weak overlap), contradiction
dominates and triggers the gate, resolvability is judged apart from support,
and revisions are re-assessable.
"""

from __future__ import annotations

from app.claims import (
    CitationMetadata,
    EntailmentLabel,
    GateDecision,
    Resolvability,
    assess_claim,
    assess_resolvability,
    extract_atomic_claims,
    publication_gate,
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
    """A passage merely sharing a couple of words does not SUPPORT the claim.

    This is the core M5 guard: word overlap must not equal verification.
    """
    claim = "Inhibiting kinase X reduces tumor growth in AML cells."
    passages = ["This unrelated review discusses cardiac tissue growth."]
    result = assess_claim(claim, passages)
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.supporting_passages == ()


def test_strong_topical_overlap_supports() -> None:
    """A passage restating the claim's content SUPPORTS it, with provenance."""
    claim = "Inhibiting kinase X reduces tumor growth in AML cells."
    passages = [
        "Kinase X inhibition reduces tumor growth across several AML cells."
    ]
    result = assess_claim(claim, passages)
    assert result.label is EntailmentLabel.SUPPORTS
    assert result.supporting_passages == tuple(passages)
    assert result.assessor  # provenance recorded


def test_contradiction_dominates_over_support() -> None:
    """A contradicting passage yields CONTRADICTS even amid supporting text."""
    claim = "Inhibiting kinase X reduces tumor growth in AML cells."
    passages = [
        "Kinase X inhibition reduces tumor growth in AML cells.",
        "Kinase X inhibition did not reduce tumor growth in AML cells.",
    ]
    result = assess_claim(claim, passages)
    assert result.label is EntailmentLabel.CONTRADICTS
    assert result.contradicting_passages
    assert result.is_fundamental_failure


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


# --- Publication gate -------------------------------------------------------


def test_gate_blocks_contradicted_hypothesis() -> None:
    """A contradicted fundamental claim blocks publication."""
    assessments = [
        assess_claim(
            "Kinase X inhibition reduces AML tumor growth.",
            ["Kinase X inhibition did not reduce AML tumor growth."],
        )
    ]
    result = publication_gate(assessments)
    assert result.decision is GateDecision.BLOCK
    assert result.contradicted_claims


def test_gate_blocks_unsupported_unless_speculative_allowed() -> None:
    """Unsupported claims block by default but pass as labeled speculation."""
    assessments = [
        assess_claim(
            "Kinase X inhibition reduces AML tumor growth.",
            ["An unrelated passage about photosynthesis in plants."],
        )
    ]
    assert publication_gate(assessments).decision is GateDecision.BLOCK
    allowed = publication_gate(assessments, allow_speculative=True)
    assert allowed.decision is GateDecision.ALLOW
    assert allowed.unsupported_claims  # surfaced as speculative


def test_gate_allows_supported_hypothesis() -> None:
    """A hypothesis whose claims are supported publishes."""
    assessments = [
        assess_claim(
            "Kinase X inhibition reduces AML tumor growth.",
            ["Kinase X inhibition reduces AML tumor growth in cell lines."],
        )
    ]
    result = publication_gate(assessments)
    assert result.decision is GateDecision.ALLOW


def test_gate_blocks_hypothesis_with_no_claims() -> None:
    """A hypothesis with no assessable claims cannot publish."""
    assert publication_gate([]).decision is GateDecision.BLOCK


def test_revision_is_reassessed() -> None:
    """Re-assessing a revised claim against new evidence updates the verdict.

    A claim first contradicted becomes supported once the hypothesis is revised
    and matched to confirming evidence — the recheck path (M5).
    """
    claim = "Kinase X inhibition reduces AML tumor growth."
    contradicted = assess_claim(
        claim, ["Kinase X inhibition did not reduce AML tumor growth."]
    )
    assert contradicted.label is EntailmentLabel.CONTRADICTS

    revised = "Combined kinase X and cofactor W inhibition reduces AML growth."
    supported = assess_claim(
        revised,
        [
            "Combined kinase X and cofactor W inhibition reduces AML growth "
            "durably in patient-derived cells."
        ],
    )
    assert supported.label is EntailmentLabel.SUPPORTS
