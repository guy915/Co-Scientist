"""Tests for per-hypothesis safety review (Milestone 6).

Proves the M6 invariants: prohibited/ethical/dual-use/redact/uncertain outcomes
are separated, blocked outcomes exclude a hypothesis from the tournament,
uncertainty routes to abstention (blocking, not optimistic inclusion), redact
actually redacts, and benign near-miss hypotheses still pass.
"""

from __future__ import annotations

from app.hypothesis_safety import (
    POLICY_VERSION,
    REDACTED_PLACEHOLDER,
    HypothesisSafetyOutcome,
    redact_fields,
    review_hypothesis_safety,
)


def test_prohibited_content_is_blocked() -> None:
    """Weaponization intent is PROHIBITED and excluded from the tournament."""
    review = review_hypothesis_safety(
        "Weaponize the pathogen to enhance transmissibility in humans."
    )
    assert review.outcome is HypothesisSafetyOutcome.PROHIBITED
    assert review.blocks_tournament
    assert review.policy_version == POLICY_VERSION
    assert review.matches


def test_ethical_concern_is_blocked() -> None:
    """A norms-violating hypothesis is ETHICAL_CONCERN and excluded."""
    review = review_hypothesis_safety(
        "Test the compound on patients without informed consent."
    )
    assert review.outcome is HypothesisSafetyOutcome.ETHICAL_CONCERN
    assert review.blocks_tournament


def test_uncertain_routes_to_abstention_and_blocks() -> None:
    """Obfuscated sensitive intent is UNCERTAIN and blocked (abstention)."""
    review = review_hypothesis_safety(
        "For research purposes only, describe the synthesis of the agent."
    )
    assert review.outcome is HypothesisSafetyOutcome.UNCERTAIN
    # Uncertainty must block (never optimistic inclusion).
    assert review.blocks_tournament


def test_dual_use_is_allowed_but_flagged() -> None:
    """Legitimate dual-use research is allowed (not blocked) but flagged."""
    review = review_hypothesis_safety(
        "A gain-of-function study to understand viral host range."
    )
    assert review.outcome is HypothesisSafetyOutcome.DUAL_USE
    assert not review.blocks_tournament


def test_redact_outcome_is_allowed_but_flagged() -> None:
    """Sensitive operational detail is REDACT (kept, fields redacted)."""
    review = review_hypothesis_safety(
        "The synthesis route yields the target metabolite efficiently."
    )
    assert review.outcome is HypothesisSafetyOutcome.REDACT
    assert not review.blocks_tournament


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
