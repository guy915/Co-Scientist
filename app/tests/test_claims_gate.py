"""Publication gating over assessed claims (M5).

The gate half of ``app.claims``, split out of ``test_claims.py`` when that
file passed the module-size budget; the entailment, retrieval, provenance
and resolvability halves stay there.

What the gate decides: a hypothesis whose *categorical* claims the evidence
contradicts is withheld, one whose merely-insufficient claims are labeled
speculation is not, and a contradicted proposal publishes carrying the
contradiction rather than disappearing.
"""

from __future__ import annotations

from app.claims import (
    ClaimAssessment,
    EntailmentLabel,
    GateDecision,
    as_passages,
    assess_claim,
    publication_gate,
)

# --- Publication gate -------------------------------------------------------


_CONTRADICTED_CLAIM = "Kinase X inhibition reduces AML tumor growth."


def _contradicted_assessments() -> list[ClaimAssessment]:
    """One claim the evidence flatly contradicts."""
    return [
        assess_claim(
            _CONTRADICTED_CLAIM,
            as_passages(
                ["Kinase X inhibition did not reduce AML tumor growth."]
            ),
        )
    ]


def test_gate_blocks_contradicted_hypothesis() -> None:
    """A contradicted fundamental claim blocks publication."""
    assessments = _contradicted_assessments()
    result = publication_gate(assessments)
    assert result.decision is GateDecision.BLOCK
    assert result.contradicted_claims
    # The rank-and-publish config (the pre-ranking call site) loosens support
    # requirements but must still withhold a contradicted idea: contradiction
    # of a categorical claim is a hard block independent of
    # allow_speculative/require_supported_claim. allow_speculative is a
    # blanket "treat every insufficient claim as speculation" switch, so
    # letting it soften contradictions too would delete contradiction
    # blocking from the pre-ranking gate, which passes it True.
    loosened = publication_gate(
        assessments, allow_speculative=True, require_supported_claim=False
    )
    assert loosened.decision is GateDecision.BLOCK


def test_gate_allows_a_contradicted_claim_the_idea_only_proposes() -> None:
    """Contradicting a proposal is a verdict on it, not grounds to hide it.

    Only a claim the hypothesis asserts as established fact -- its
    literature grounding and mechanism -- blocks when the evidence goes
    against it. The statement and expected effect are the idea itself:
    evidence pointing the other way is exactly the finding the reader came
    for, so the idea publishes carrying the contradiction rather than
    disappearing from the report.
    """
    assessments = _contradicted_assessments()
    result = publication_gate(
        assessments,
        explicitly_speculative_claims={_CONTRADICTED_CLAIM},
    )
    assert result.decision is GateDecision.ALLOW
    # Still named on the result: the gate lets it through, it does not
    # pretend the contradiction is absent.
    assert result.contradicted_claims == (_CONTRADICTED_CLAIM,)
    assert "contradicted" in result.reason


def test_gate_blocks_a_categorical_contradiction_beside_a_speculative_one() -> (
    None
):
    """One contradicted categorical claim blocks whatever else is proposed."""
    grounding = "Kinase X inhibition reduces AML relapse rates."
    assessments = [
        *_contradicted_assessments(),
        assess_claim(
            grounding,
            as_passages(
                [
                    "Kinase X inhibition did not reduce AML relapse rates; "
                    "there was no significant effect on relapse."
                ]
            ),
        ),
    ]
    result = publication_gate(
        assessments,
        explicitly_speculative_claims={_CONTRADICTED_CLAIM},
    )
    assert result.decision is GateDecision.BLOCK
    # The block names the categorical claim it is actually about, not the
    # proposal the gate just decided to tolerate.
    assert result.failed_claims == (grounding,)


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


def test_gate_counts_partial_as_a_supported_claim() -> None:
    """A partial (near-miss) claim satisfies the require-supported-claim gate.

    Partial evidence is relevant and consistent, so it does not leave the
    hypothesis wholly unsupported -- the gate must not block it even when a
    supported claim is required.
    """
    partial = assess_claim(
        "Inhibiting kinase X reduces tumor growth in AML cells.",
        as_passages(
            [
                "Kinase enzymes regulate cellular growth under diverse "
                "metabolic conditions across many organisms."
            ]
        ),
    )
    assert partial.label is EntailmentLabel.PARTIAL
    result = publication_gate([partial], require_supported_claim=True)
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
