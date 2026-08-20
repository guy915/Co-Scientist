"""The unsupported-claim rate, over verdicts a run already recorded.

The driving half is exercised by running the eval itself (and by the
other drivers' offline sweeps); what is pinned here is the reduction,
because every way this metric could quietly lie is in the arithmetic --
a rate over an empty denominator, or "supported" drifting away from what
the report means by it.
"""

from __future__ import annotations

from evaluations.claim_support_eval import score_claims


def test_a_run_with_no_assessed_claims_has_no_rate() -> None:
    """Nothing assessed is not perfect support, and must not print as it."""
    metrics = score_claims([{"assessed_claims": 0, "verified_claims": 0}])

    assert metrics["unsupported_claim_rate"] is None
    assert metrics["unverified_idea_rate"] is None


def test_the_rate_counts_claims_not_ideas() -> None:
    """One idea making ten unsupported claims is ten unsupported claims."""
    metrics = score_claims(
        [
            {"assessed_claims": 10, "verified_claims": 0},
            {"assessed_claims": 2, "verified_claims": 2},
        ]
    )

    assert metrics["claims_assessed"] == 12
    assert metrics["claims_supported"] == 2
    assert metrics["unsupported_claim_rate"] == round(10 / 12, 4)


def test_the_idea_rate_counts_ideas_with_nothing_behind_them() -> None:
    """What a reader sees badged Unverified is per idea, not per claim.

    An idea with one supported claim out of five is not unverified, so a
    retrieval change that only deepens already-supported ideas moves the
    claim rate and leaves this one alone -- which is the point of
    reporting both.
    """
    metrics = score_claims(
        [
            {"assessed_claims": 5, "verified_claims": 1},
            {"assessed_claims": 5, "verified_claims": 0},
            {"assessed_claims": 0, "verified_claims": 0},
        ]
    )

    # The claimless idea is outside the denominator entirely.
    assert metrics["ideas"] == 3
    assert metrics["ideas_with_assessed_claims"] == 2
    assert metrics["unverified_idea_rate"] == 0.5
