"""Scaling-curve and controlled-ablation evaluation tests."""

from evaluations.scaling_eval import ablation_summary, scaling_curve


def test_scaling_curve_orders_compute_and_uses_expert_quality() -> None:
    snapshots = [
        {
            "run_id": "large",
            "goal_id": "g1",
            "metrics": {"llm_calls": 20, "tasks": 8, "cost_usd": 2.0},
            "hypotheses": [
                {
                    "text": "kinase mechanism with rescue control",
                    "elo_rating": 1320,
                    "expert_score": 4.5,
                    "verified_claims": 3,
                    "assessed_claims": 4,
                }
            ],
        },
        {
            "run_id": "small",
            "goal_id": "g1",
            "metrics": {"llm_calls": 5, "tasks": 2, "cost_usd": 0.5},
            "hypotheses": [
                {
                    "text": "initial kinase idea",
                    "elo_rating": 1200,
                    "expert_score": 3.0,
                    "verified_claims": 1,
                    "assessed_claims": 2,
                }
            ],
        },
    ]

    curve = scaling_curve(snapshots)

    assert [point["run_id"] for point in curve] == ["small", "large"]
    assert curve[1]["top10_expert_quality"] == 4.5
    assert curve[1]["verified_claim_ratio"] == 0.75
    assert curve[1]["best_elo"] == 1320


def test_ablation_summary_counts_only_fully_paired_goals() -> None:
    records = [
        {
            "goal_id": "g1",
            "arm": "baseline",
            "expert_quality": 3.0,
            "diversity": 0.7,
            "verified_claim_ratio": 0.5,
            "cost_usd": 1.0,
            "latency_seconds": 10.0,
        },
        {
            "goal_id": "g1",
            "arm": "no_debate",
            "expert_quality": 2.0,
            "diversity": 0.6,
            "verified_claim_ratio": 0.4,
            "cost_usd": 0.8,
            "latency_seconds": 8.0,
        },
        {
            "goal_id": "g2",
            "arm": "baseline",
            "expert_quality": 4.0,
            "diversity": 0.8,
            "verified_claim_ratio": 0.7,
            "cost_usd": 1.1,
            "latency_seconds": 11.0,
        },
    ]

    summary = ablation_summary(records)

    assert summary["paired_goal_count"] == 1
    assert summary["arms"]["baseline"]["expert_quality"] == 3.5
    assert summary["arms"]["no_debate"]["n"] == 1
