"""Controlled feature-ablation driver tests (L11).

Runs the offline path only: two arms across one goal, proving the driver's
wiring, per-arm record shape, and ``ablation_summary`` pairing end to end
without a provider key or network. The live sweep (where the toggles
actually change literature/tool behavior) is the operator's explicit
``--live`` invocation, never run here -- see the module docstring for why an
offline run cannot show a real ablation effect.
"""

from __future__ import annotations

from evaluations.ablation_driver import run_ablation_sweep

_GOALS = (
    (
        "test-goal-1",
        "Propose a mechanism for acquired resistance to EGFR tyrosine "
        "kinase inhibitors in EGFR-mutant lung adenocarcinoma.",
    ),
)
_ARMS = {
    "baseline": {},
    "no_web_search": {"enable_web_search": False},
}


def test_offline_ablation_sweep_pairs_every_goal_across_arms() -> None:
    report = run_ablation_sweep(_GOALS, "express", live=False, arms=_ARMS)

    assert report["mode"] == "offline"
    assert report["arms_run"] == sorted(_ARMS)
    assert len(report["driven"]) == len(_GOALS) * len(_ARMS)
    for arm in report["driven"]:
        assert arm["completed"], arm
        assert arm["used_real_backend"] is False

    summary = report["summary"]
    assert summary["paired_goal_count"] == 1
    assert set(summary["arms"]) == set(_ARMS)


def test_ablation_records_carry_real_floats_ablation_summary_requires() -> None:
    """``ablation_summary`` reads cost/latency/diversity unconditionally.

    A None here would raise inside ``ablation_summary`` -- see its
    ``float(item["cost_usd"])`` etc, which are not None-guarded the way
    ``expert_quality``/``verified_claim_ratio`` are.
    """
    report = run_ablation_sweep(_GOALS, "express", live=False, arms=_ARMS)
    for record in report["records"]:
        assert isinstance(record["cost_usd"], float)
        assert isinstance(record["latency_seconds"], float)
        assert isinstance(record["diversity"], float)
        assert record["cost_usd"] == 0.0, "offline calls must cost nothing"


def test_documents_the_unreachable_meta_review_and_strategy_arms() -> None:
    report = run_ablation_sweep(_GOALS, "express", live=False, arms=_ARMS)
    assert "no_meta_review" in report["unreachable_arms"]
    assert "no_debate_strategy" in report["unreachable_arms"]
