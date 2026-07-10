"""Tests for reproducible hypothesis-quality metrics (Milestone 8)."""

from __future__ import annotations

from evaluations.metrics import (
    generation_vs_evolution_yield,
    hypothesis_diversity,
)


def test_identical_pool_has_zero_diversity() -> None:
    """A pool of identical hypotheses has diversity 0."""
    assert hypothesis_diversity(["same idea here", "same idea here"]) == 0.0


def test_disjoint_pool_has_max_diversity() -> None:
    """Lexically disjoint hypotheses have diversity 1.0."""
    assert (
        hypothesis_diversity(
            ["kinase inhibition apoptosis", "quantum gravity spacetime"]
        )
        == 1.0
    )


def test_singleton_pool_diversity_is_zero() -> None:
    """A pool with fewer than two hypotheses has no pairs (0.0)."""
    assert hypothesis_diversity(["only one"]) == 0.0
    assert hypothesis_diversity([]) == 0.0


def test_generation_vs_evolution_yield_split() -> None:
    """The yield report splits counts and diversity by origin."""
    hyps = [
        {"origin": "generation", "text": "kinase inhibition reduces growth"},
        {"origin": "generation", "text": "receptor blockade restores immunity"},
        {"origin": "evolution", "text": "combined kinase and cofactor therapy"},
    ]
    report = generation_vs_evolution_yield(hyps)
    assert report["counts"] == {"generation": 2, "evolution": 1}
    assert report["n"] == 3
    assert "generation" in report["diversity_by_origin"]
    assert 0.0 <= report["overall_diversity"] <= 1.0
