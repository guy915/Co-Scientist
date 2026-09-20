"""Test publication rules and stricter artifact-completeness prerequisites.

A complete artifact follows the live predicates; an incomplete export must not
be accepted merely because the evaluator cannot reconstruct the live decision.
"""

from typing import Any

import pytest

from evaluations.release_gate import scientific_release_gate


def _ready_artifact() -> dict[str, Any]:
    """A run with one publishable idea and nothing held against it."""
    return {
        "hypotheses": [
            {"id": "h1", "status": "ranked", "safety_status": "allow"}
        ],
        "safety": [{"id": 1, "stage": "final", "decision": "allow"}],
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
    artifact["safety"] = [
        {
            "id": 1,
            "stage": "final",
            "decision": "hold",
            "requires_review": True,
            "resolution": None,
        }
    ]

    result = scientific_release_gate(artifact)

    assert result["decision"] == "withhold"
    assert "final safety screen withheld publication" in result["reasons"]


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


def test_missing_final_screen_is_not_evidence_of_safe_publication() -> None:
    artifact = _ready_artifact()
    artifact["safety"] = [{"stage": "intake", "decision": "allow"}]
    assert scientific_release_gate(artifact)["decision"] == "withhold"


def test_final_block_without_review_flag_still_withholds() -> None:
    artifact = _ready_artifact()
    artifact["safety"] = [
        {
            "id": 1,
            "stage": "final",
            "decision": "block",
            "requires_review": False,
        }
    ]
    assert scientific_release_gate(artifact)["decision"] == "withhold"


def test_pending_and_legacy_hypotheses_use_the_live_safety_classifier() -> None:
    from app.hypothesis_safety import review_hypothesis_safety

    statement = (
        "Engineer smallpox virus to enhance human-to-human "
        "transmission and lethality"
    )
    assert review_hypothesis_safety(statement).blocks_tournament
    for status in (None, "pending"):
        artifact = _ready_artifact()
        artifact["safety"] = [{"id": 1, "stage": "final", "decision": "allow"}]
        artifact["hypotheses"] = [
            {
                "id": "h1",
                "status": "ranked",
                "statement": statement,
                "safety_status": status,
            }
        ]
        result = scientific_release_gate(artifact)
        assert result["releasable_hypotheses"] == 0
        assert result["decision"] == "withhold"


@pytest.mark.parametrize("status", [None, "pending"])
def test_benign_legacy_hypothesis_still_publishes(status: str | None) -> None:
    artifact = _ready_artifact()
    artifact["hypotheses"][0].update(
        safety_status=status, statement="Study mitochondrial biogenesis."
    )
    assert scientific_release_gate(artifact)["decision"] == "release"


def test_missing_legacy_content_is_not_screening_evidence() -> None:
    artifact = _ready_artifact()
    artifact["hypotheses"][0].pop("safety_status")
    assert scientific_release_gate(artifact)["decision"] == "withhold"


@pytest.mark.parametrize("decision", ["hold", "block", "unknown"])
def test_latest_final_verdict_controls_even_after_approval(
    decision: str,
) -> None:
    artifact = _ready_artifact()
    artifact["safety"].insert(
        0,
        {
            "id": 2,
            "stage": "final",
            "decision": decision,
            "resolution": "approved",
        },
    )
    assert scientific_release_gate(artifact)["decision"] == "withhold"


def test_new_final_allow_after_approved_hold_releases() -> None:
    artifact = _ready_artifact()
    artifact["safety"] = [
        {"id": 2, "stage": "final", "decision": "allow"},
        {
            "id": 1,
            "stage": "final",
            "decision": "hold",
            "requires_review": True,
            "resolution": "approved",
        },
    ]
    assert scientific_release_gate(artifact)["decision"] == "release"


def test_hypothesis_review_does_not_block_other_released_ideas() -> None:
    artifact = _ready_artifact()
    artifact["safety"].append(
        {
            "id": 2,
            "stage": "hypothesis",
            "decision": "hold",
            "requires_review": True,
        }
    )
    assert scientific_release_gate(artifact)["decision"] == "release"


@pytest.mark.parametrize(
    "matches,expected", [(["dual-use"], "release"), ([], "withhold")]
)
def test_final_redaction_requires_actionable_matches(
    matches: list[str],
    expected: str,
) -> None:
    artifact = _ready_artifact()
    artifact["safety"] = [
        {
            "id": 1,
            "stage": "final",
            "decision": "redact",
            "requires_review": True,
            "matches": matches,
        }
    ]
    assert scientific_release_gate(artifact)["decision"] == expected


def test_missing_final_record_id_withholds() -> None:
    artifact = _ready_artifact()
    artifact["safety"][0].pop("id")
    assert scientific_release_gate(artifact)["decision"] == "withhold"
