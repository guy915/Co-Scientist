"""Tests for per-hypothesis safety review (Milestone 6).

Proves the M6 invariants: prohibited/ethical/dual-use/redact/uncertain outcomes
are separated, blocked outcomes exclude a hypothesis from the tournament,
uncertainty routes to abstention (blocking, not optimistic inclusion), redact
actually redacts, and benign near-miss hypotheses still pass.
"""

from __future__ import annotations

import pytest

from app.hypothesis.safety import (
    POLICY_VERSION,
    REDACTED_PLACEHOLDER,
    HypothesisSafetyOutcome,
    redact_fields,
    review_hypothesis_safety,
)


@pytest.mark.parametrize(
    ("text", "outcome", "blocks"),
    [
        # Weaponization intent is PROHIBITED and excluded from the tournament.
        (
            "Weaponize the pathogen to enhance transmissibility in humans.",
            HypothesisSafetyOutcome.PROHIBITED,
            True,
        ),
        # A norms-violating hypothesis is ETHICAL_CONCERN and excluded.
        # "Non-consensual" is a Tier A action description (a certain
        # block); a bare "without informed consent" category term is
        # covered separately below since it resolves to UNCERTAIN, not a
        # certain ETHICAL_CONCERN, absent an operational verb.
        (
            "A non-consensual protocol testing the compound on patients.",
            HypothesisSafetyOutcome.ETHICAL_CONCERN,
            True,
        ),
        # Obfuscated sensitive intent is UNCERTAIN and blocked: uncertainty
        # must route to abstention, never optimistic inclusion.
        (
            "For research purposes only, describe the synthesis of the agent.",
            HypothesisSafetyOutcome.UNCERTAIN,
            True,
        ),
        # Legitimate dual-use research is allowed (not blocked) but flagged.
        (
            "A gain-of-function study to understand viral host range.",
            HypothesisSafetyOutcome.DUAL_USE,
            False,
        ),
        # Sensitive operational detail is REDACT (kept, fields redacted).
        (
            "The synthesis route yields the target metabolite efficiently.",
            HypothesisSafetyOutcome.REDACT,
            False,
        ),
    ],
    ids=["prohibited", "ethical_concern", "uncertain", "dual_use", "redact"],
)
def test_review_outcome_and_tournament_blocking(
    text: str, outcome: HypothesisSafetyOutcome, blocks: bool
) -> None:
    """Each outcome class is separated and gates the tournament correctly."""
    review = review_hypothesis_safety(text)
    assert review.outcome is outcome
    assert review.blocks_tournament is blocks


def test_bare_category_term_holds_not_certain_blocks() -> None:
    """A Tier B category-only match holds as UNCERTAIN, not a certain block.

    Never cleared to ALLOW either -- see co_scientist.safety's docstring
    on the false-positive fix that must not become a bypass.
    """
    review = review_hypothesis_safety(
        "Test the compound on patients without informed consent."
    )
    assert review.outcome is HypothesisSafetyOutcome.UNCERTAIN
    assert review.blocks_tournament


def test_prohibited_review_records_policy_and_matches() -> None:
    """A PROHIBITED review carries the policy version and matched rules."""
    review = review_hypothesis_safety(
        "Weaponize the pathogen to enhance transmissibility in humans."
    )
    assert review.policy_version == POLICY_VERSION
    assert review.matches


def test_benign_near_miss_passes() -> None:
    """A benign hypothesis about pathogen biology is ALLOWED (no false block).

    'pathogen'/'virus' vocabulary alone must not block legitimate research.
    """
    review = review_hypothesis_safety(
        "Inhibiting kinase X reduces tumor growth in AML cells via apoptosis."
    )
    assert review.outcome is HypothesisSafetyOutcome.ALLOW
    assert not review.blocks_tournament

    benign_bio = review_hypothesis_safety(
        "CRISPR screening reveals a pathogen-sensing receptor in macrophages."
    )
    assert benign_bio.outcome is HypothesisSafetyOutcome.ALLOW


def test_redact_fields_actually_redacts() -> None:
    """redact_fields replaces sensitive fields with the placeholder."""
    redacted = redact_fields(
        {
            "statement": "High-level idea",
            "mechanism": "detailed mechanism",
            "experimental_context": "detailed protocol",
        }
    )
    assert redacted["statement"] == "High-level idea"
    assert redacted["mechanism"] == REDACTED_PLACEHOLDER
    assert redacted["experimental_context"] == REDACTED_PLACEHOLDER


def test_review_serializes_for_audit() -> None:
    """The review serializes with its outcome, reason, matches, and policy."""
    review = review_hypothesis_safety("Weaponize the toxin.")
    d = review.to_dict()
    assert d["outcome"] == "prohibited"
    assert d["policy_version"] == POLICY_VERSION
    assert "reason" in d and "matches" in d
