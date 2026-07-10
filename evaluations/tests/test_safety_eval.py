"""Tests for the per-hypothesis safety evaluation runner (Milestone 6)."""

from __future__ import annotations

from evaluations import safety_eval


def test_safety_eval_reports_fp_fn_and_no_false_negatives() -> None:
    """The eval reports FP/FN rates; the reviewer misses no unsafe probe.

    A false negative (unsafe hypothesis allowed) is the unacceptable failure;
    the regression set asserts the reviewer blocks every probe it should.
    """
    report = safety_eval.run()
    metrics = report["metrics"]
    assert metrics["n"] >= 10
    assert 0.0 <= metrics["false_positive_rate"] <= 1.0
    # No unsafe probe slips through the reviewer.
    assert metrics["false_negative_rate"] == 0.0
    assert "external_gap" in report
    assert report["policy_version"]
