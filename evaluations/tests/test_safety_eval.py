"""Tests for the per-hypothesis safety evaluation runner (Milestone 6)."""

from __future__ import annotations

from evaluations import safety_eval


def test_safety_eval_reports_both_arms() -> None:
    """The eval scores both a must-block and a must-allow set."""
    report = safety_eval.run()
    metrics = report["metrics"]
    assert metrics["n_adversarial"] >= 15
    assert metrics["n_control"] >= 25
    assert 0.0 <= metrics["false_positive_rate"] <= 1.0
    assert 0.0 <= metrics["false_negative_rate"] <= 1.0
    assert "external_gap" in report
    assert report["policy_version"]
    assert report["layer"].startswith("deterministic")


def test_easy_baseline_stays_fully_correct() -> None:
    """The original, literal-trigger probes are a non-regressing floor.

    These are the items the regex classifier was written against; a
    regression here means the classifier itself changed, not that the
    dataset got harder.
    """
    report = safety_eval.run()
    easy = report["metrics"]["by_difficulty"]["easy"]
    assert easy["false_positive_rate"] == 0.0
    assert easy["false_negative_rate"] == 0.0


def test_hard_split_is_measured_not_gated() -> None:
    """The adversarial/control hard items report real numbers, not a pin.

    This suite exists to measure the deterministic layer's boundary, not to
    stay green: a hard item that evades detection or a benign item that
    gets wrongly blocked must show up in the rate, never be dropped or have
    a threshold tuned around it. Only shape and bounds are asserted here.
    """
    report = safety_eval.run()
    hard = report["metrics"]["by_difficulty"]["hard"]
    assert hard["n"] > 0
    assert 0.0 <= hard["false_positive_rate"] <= 1.0
    assert 0.0 <= hard["false_negative_rate"] <= 1.0


def test_per_category_breakdown_covers_every_item() -> None:
    """Every scored item lands in exactly one category bucket."""
    report = safety_eval.run()
    per_category = report["metrics"]["per_category"]
    total = sum(bucket["total"] for bucket in per_category.values())
    assert total == report["metrics"]["n"]
