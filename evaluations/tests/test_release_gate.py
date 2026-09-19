"""Scientific release-gate tests.

The gate applies the live publication rules rather than its own (``L1``),
so these are also the regression tests for those rules: each one names the
live behavior it pins, and a change to publication that does not break one
of these is a change this evaluator would not have caught.
"""

from typing import Any

from evaluations.release_gate import scientific_release_gate


def _ready_artifact() -> dict[str, Any]:
    """A run with one publishable idea and nothing held against it."""
    return {
        "hypotheses": [{"id": "h1", "status": "ranked"}],
        "safety": [],
        "claims": [
            {"hypothesis_id": "h1", "label": "supports"},
            {"hypothesis_id": "h1", "label": "supports"},
        ],
        "provenance": {
            "model": "provider/model",
            "policy_version": "v2",
            "retrieval_sources": ["pubmed"],
        },
    }


def test_release_gate_releases_scientifically_ready_artifact() -> None:
    result = scientific_release_gate(_ready_artifact())
    assert result["decision"] == "release"
    assert result["reasons"] == []


def test_an_unresolved_safety_review_withholds_the_report() -> None:
    """Live: a report-level block or hold withholds the whole report."""
    artifact = _ready_artifact()
    artifact["safety"] = [{"requires_review": True, "resolution": None}]

    result = scientific_release_gate(artifact)

    assert result["decision"] == "withhold"
    assert "unresolved safety review" in result["reasons"]


def test_a_contradicted_idea_is_dropped_not_published() -> None:
    """Live: contradicted ideas are withheld entirely, unlike unsupported."""
    artifact = _ready_artifact()
    artifact["claims"] = [{"hypothesis_id": "h1", "label": "contradicts"}]

    result = scientific_release_gate(artifact)

    assert result["contradicted_hypotheses"] == 1
    assert result["releasable_hypotheses"] == 0
    assert result["decision"] == "withhold"
    assert "no releasable hypotheses" in result["reasons"]


def test_a_blocked_idea_is_dropped() -> None:
    """Live: a blocking safety status keeps an idea out of the report."""
    artifact = _ready_artifact()
    artifact["hypotheses"] = [
        {"id": "h1", "status": "ranked", "safety_status": "prohibited"}
    ]

    result = scientific_release_gate(artifact)

    assert result["releasable_hypotheses"] == 0
    assert result["decision"] == "withhold"


def test_a_contradicted_speculative_proposal_is_still_published() -> None:
    """A contradicted proposal stays visible, as in live publication."""
    artifact = _ready_artifact()
    artifact["claims"] = [
        {
            "hypothesis_id": "h1",
            "label": "contradicts",
            "claim_role": "speculative",
        }
    ]

    result = scientific_release_gate(artifact)

    assert result["decision"] == "release"
    assert result["releasable_hypotheses"] == 1
    assert result["contradicted_hypotheses"] == 0


def test_a_categorical_contradiction_still_blocks_a_speculative_idea() -> None:
    """A proposal exemption cannot override a contradicted factual claim."""
    artifact = _ready_artifact()
    artifact["claims"] = [
        {
            "hypothesis_id": "h1",
            "label": "contradicts",
            "claim_role": role,
        }
        for role in ("speculative", "categorical")
    ]

    result = scientific_release_gate(artifact)

    assert result["decision"] == "withhold"
    assert result["releasable_hypotheses"] == 0
    assert result["contradicted_hypotheses"] == 1


def test_a_rejected_or_duplicate_idea_is_dropped() -> None:
    """Live: both excluded statuses keep an idea out of synthesis."""
    artifact = _ready_artifact()
    artifact["hypotheses"] = [
        {"id": "h1", "status": "rejected"},
        {"id": "h2", "status": "duplicate"},
    ]

    result = scientific_release_gate(artifact)

    assert result["releasable_hypotheses"] == 0


def test_an_unsupported_idea_is_published_not_withheld() -> None:
    """Live: unsupported-but-uncontradicted publishes with a badge.

    The rule this evaluator used to get wrong. It demanded an 80% verified
    ratio, which production has never applied -- so the gate withheld
    artifacts production would publish, and a green suite proved nothing
    about live behavior. The ratio is still reported.
    """
    artifact = _ready_artifact()
    artifact["claims"] = [{"hypothesis_id": "h1", "label": "unsupported"}]

    result = scientific_release_gate(artifact)

    assert result["decision"] == "release"
    assert result["verified_claim_ratio"] == 0.0


def test_missing_provenance_is_reported_not_enforced() -> None:
    """Nothing in the live path withholds science over a missing field."""
    artifact = _ready_artifact()
    artifact["provenance"] = {}

    result = scientific_release_gate(artifact)

    assert result["decision"] == "release"
    assert sorted(result["missing_provenance"]) == [
        "model",
        "policy_version",
        "retrieval_sources",
    ]


def test_an_empty_run_is_withheld() -> None:
    """Live: an empty leaderboard hard-blocks release."""
    result = scientific_release_gate(
        {"hypotheses": [], "safety": [], "claims": [], "provenance": {}}
    )

    assert result["decision"] == "withhold"
    assert "no releasable hypotheses" in result["reasons"]
