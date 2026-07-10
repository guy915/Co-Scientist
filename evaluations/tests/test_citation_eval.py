"""Tests for the citation/claim-entailment evaluation runner (Milestone 5)."""

from __future__ import annotations

from evaluations import citation_eval


def test_eval_runs_and_reports_metrics() -> None:
    """The eval produces a metrics report over the labeled dataset."""
    report = citation_eval.run()
    metrics = report["metrics"]
    assert metrics["n"] >= 10
    # Every label is exercised (precision/recall present for each).
    for label in ("supports", "contradicts", "insufficient"):
        assert label in metrics["per_label"]
    # Metrics are well-formed probabilities.
    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert 0.0 <= metrics["contradiction_recall"] <= 1.0
    # The honest external gap is recorded, not hidden.
    assert "external_gap" in report
