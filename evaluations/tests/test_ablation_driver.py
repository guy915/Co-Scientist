"""Controlled feature-ablation driver tests (L11).

Runs the offline path only: two arms across one goal, proving the driver's
wiring, per-arm record shape, and ``ablation_summary`` pairing end to end
without a provider key or network. The live sweep (where the toggles
actually change literature/tool behavior) is the operator's explicit
``--live`` invocation, never run here -- see the module docstring for why an
offline run cannot show a real ablation effect.
"""

from __future__ import annotations

from evaluations.ablation_driver import (
    PUBLISHED_BASELINES,
    PUBLISHED_BASELINES_UNQUANTIFIED,
    run_ablation_sweep,
)

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


def test_published_baselines_cover_reflection_evolution_meta_review() -> None:
    """Google's ablation numbers (R11-8) cover the unreachable arms.

    Plus the reachable Reflection search-tool arm.
    """
    assert set(PUBLISHED_BASELINES) == {
        "reflection_search_tool",
        "evolution",
        "meta_review",
    }
    reflection = PUBLISHED_BASELINES["reflection_search_tool"]
    assert reflection["metrics"]["novelty"] == {
        "baseline": 6.14,
        "ablated": 2.38,
    }
    # Not uniformly directional: correctness improves while novelty
    # collapses. Both numbers must survive, never smoothed into one story.
    assert (
        reflection["metrics"]["correctness"]["baseline"]
        < (reflection["metrics"]["correctness"]["ablated"])
    )
    assert (
        reflection["metrics"]["novelty"]["baseline"]
        > (reflection["metrics"]["novelty"]["ablated"])
    )


def test_published_baselines_unquantified_names_ranking_and_proximity() -> None:
    assert set(PUBLISHED_BASELINES_UNQUANTIFIED) == {
        "ranking_prompt",
        "proximity",
    }


def test_published_baselines_are_carried_in_the_report_unmodified() -> None:
    """Reference data only, never fed into the computed ``summary``.

    ``summary`` reads only the driven ``records``.
    """
    report = run_ablation_sweep(_GOALS, "express", live=False, arms=_ARMS)
    assert report["published_baselines"] == PUBLISHED_BASELINES
    assert (
        report["published_baselines_unquantified"]
        == PUBLISHED_BASELINES_UNQUANTIFIED
    )
    assert "published_baselines" not in report["summary"]
