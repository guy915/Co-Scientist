from __future__ import annotations

from evaluations import safety_eval


def test_safety_eval_reports_both_arms_and_the_easy_baseline_is_exact() -> None:
    report = safety_eval.run()
    metrics = report["metrics"]
    assert metrics["n_adversarial"] >= 15
    assert metrics["n_control"] >= 25
    assert report["policy_version"]
    assert "external_gap" in report
    easy = metrics["by_difficulty"]["easy"]
    assert easy["false_positive_rate"] == 0.0
    assert easy["false_negative_rate"] == 0.0
    # The hard split measures the deterministic boundary; it is not gated.
    assert metrics["by_difficulty"]["hard"]["n"] > 0
    per_category = metrics["per_category"]
    assert sum(b["total"] for b in per_category.values()) == metrics["n"]
