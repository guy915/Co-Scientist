"""Tests for scientist-in-the-loop hypotheses and reviews (Milestone 7)."""

from __future__ import annotations

import pytest

from app.human_input import (
    SCIENTIST_MANUAL_ORIGIN,
    admit_human_hypothesis,
    build_human_review,
)


def test_admitted_human_hypothesis_carries_authorship() -> None:
    """A safe scientist hypothesis is admitted with authorship provenance."""
    result = admit_human_hypothesis(
        text="Inhibiting kinase X reduces AML tumor growth via apoptosis.",
        author="dr-jane",
    )
    assert result.admitted
    assert result.hypothesis is not None
    assert result.hypothesis["origin"] == SCIENTIST_MANUAL_ORIGIN
    assert result.hypothesis["author"] == "dr-jane"
    # Enters at generation 0 with no parent, like a generated root.
    assert result.hypothesis["generation"] == 0
    assert result.hypothesis["parent_id"] is None


def test_human_hypothesis_uses_same_safety_path_no_bypass() -> None:
    """An unsafe scientist hypothesis is blocked; authorship is no bypass.

    This is the key M7 invariant: human hypotheses use the same safety path.
    """
    result = admit_human_hypothesis(
        text="Weaponize the pathogen to enhance transmissibility in humans.",
        author="dr-jane",
    )
    assert not result.admitted
    assert result.hypothesis is None
    assert result.safety_review.blocks_tournament


def test_admission_serializes_for_audit() -> None:
    """The admission decision serializes with author + safety provenance."""
    result = admit_human_hypothesis(
        text="Blocking receptor Y restores immune surveillance.",
        author="dr-lee",
    )
    d = result.to_dict()
    assert d["author"] == "dr-lee"
    assert d["admitted"] is True
    safety = d["safety"]
    assert isinstance(safety, dict) and "policy_version" in safety


def test_human_review_validates_verdict() -> None:
    """A scientist review is built with a validated verdict and authorship."""
    review = build_human_review(
        hypothesis_id="h1",
        author="dr-jane",
        verdict="Support",
        critique="Strong mechanistic grounding.",
    )
    assert review.verdict == "support"
    d = review.to_dict()
    assert d["reviewer_agent"] == "scientist"
    assert d["author"] == "dr-jane"


def test_human_review_rejects_bad_verdict() -> None:
    """An unrecognized verdict is rejected."""
    with pytest.raises(ValueError):
        build_human_review(
            hypothesis_id="h1",
            author="x",
            verdict="maybe",
            critique="",
        )
