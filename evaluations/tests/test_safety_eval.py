from __future__ import annotations

from evaluations import safety_eval


def test_safety_eval_reports_both_arms() -> None:
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
    report = safety_eval.run()
    easy = report["metrics"]["by_difficulty"]["easy"]
    assert easy["false_positive_rate"] == 0.0
    assert easy["false_negative_rate"] == 0.0


def test_hard_split_is_measured_not_gated() -> None:
    # Adversarial items measure the deterministic boundary; threshold tuning
    # must not hide mistakes.
    report = safety_eval.run()
    hard = report["metrics"]["by_difficulty"]["hard"]
    assert hard["n"] > 0
    assert 0.0 <= hard["false_positive_rate"] <= 1.0
    assert 0.0 <= hard["false_negative_rate"] <= 1.0


def test_per_category_breakdown_covers_every_item() -> None:
    report = safety_eval.run()
    per_category = report["metrics"]["per_category"]
    total = sum(bucket["total"] for bucket in per_category.values())
    assert total == report["metrics"]["n"]
