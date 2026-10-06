from __future__ import annotations

from typing import Any

import pytest

from evaluations.elo_concordance_eval import (
    _load_dataset,
    correctness_preferring_comparator,
    elo_bucket_accuracy,
    evaluate_concordance,
    inverting_comparator,
    make_coin_flip_comparator,
)
from evaluations.metrics import hypothesis_diversity
from evaluations.scaling_eval import (
    ablation_summary,
    scaling_curve,
    temporal_scaling_curve,
)


@pytest.mark.parametrize(
    ("pool", "diversity"),
    [
        (["same idea here", "same idea here"], 0.0),
        (["kinase inhibition apoptosis", "quantum gravity spacetime"], 1.0),
        ([], 0.0),
    ],
)
def test_pool_diversity(pool: list[str], diversity: float) -> None:
    assert hypothesis_diversity(pool) == diversity


def _hyp(
    hid: str,
    created_at: float,
    elo: int | None,
    generation: int = 0,
    creation_iteration: int | None = None,
) -> dict[str, Any]:
    # Absent cycle keys are omitted so legacy fixtures exercise the lineage
    # fallback.
    entry: dict[str, Any] = {
        "id": hid,
        "created_at": created_at,
        "generation": generation,
    }
    if creation_iteration is not None:
        entry["creation_iteration"] = creation_iteration
    if elo is not None:
        entry["elo_rating"] = elo
    return entry


def test_scaling_curve_orders_compute_and_uses_expert_quality() -> None:
    def snapshot(run_id: str, calls: int, elo: int, score: float, ok: int) -> Any:
        return {
            "run_id": run_id,
            "goal_id": "g1",
            "metrics": {"llm_calls": calls, "tasks": 2, "cost_usd": 0.5},
            "hypotheses": [
                {
                    "text": "kinase mechanism",
                    "elo_rating": elo,
                    "expert_score": score,
                    "verified_claims": ok,
                    "assessed_claims": 4,
                }
            ],
        }

    curve = scaling_curve(
        [
            snapshot("large", 20, 1320, 4.5, 3),
            snapshot("small", 5, 1200, 3.0, 1),
        ]
    )

    assert [point["run_id"] for point in curve] == ["small", "large"]
    assert curve[1]["top10_expert_quality"] == 4.5
    assert curve[1]["verified_claim_ratio"] == 0.75
    assert curve[1]["best_elo"] == 1320


@pytest.mark.parametrize(
    ("pool", "best_elo_by_bucket"),
    [
        # Legacy rows without cycle ordinals order by lineage depth.
        (
            [
                _hyp("a", 30.0, 1100),
                _hyp("b", 1.0, 1300, 2),
                _hyp("c", 20.0, 1200, 1),
            ],
            [1100, 1200, 1300],
        ),
        # Creation cycle outranks lineage depth: a later generation-zero idea
        # comes after earlier descendants.
        (
            [
                _hyp("seed", 1.0, 1100, 0, creation_iteration=0),
                _hyp("evolved", 2.0, 1200, 2, creation_iteration=1),
                _hyp("reborn", 3.0, 1300, 0, creation_iteration=2),
            ],
            [1100, 1200, 1300],
        ),
        (
            [
                _hyp("a", 30.0, 1100),
                _hyp("b", 10.0, 1300),
                _hyp("c", 20.0, 1200),
            ],
            [1300, 1200, 1100],
        ),
    ],
)
def test_temporal_scaling_curve_orders_by_cycle_then_lineage_then_time(
    pool: list[dict[str, Any]], best_elo_by_bucket: list[int]
) -> None:
    curve = temporal_scaling_curve(pool, bucket_count=3)

    assert [b["best_elo"] for b in curve] == best_elo_by_bucket
    assert [b["bucket"] for b in curve] == [1, 2, 3]


def test_temporal_scaling_curve_summarizes_a_bucket_of_rated_ideas() -> None:
    pool = [_hyp(f"a{i}", float(i), 1000 + i) for i in range(12)]
    pool.append(_hyp("unrated", 99.0, None))

    (bucket,) = temporal_scaling_curve(pool, bucket_count=1)

    assert bucket["n_hypotheses"] == 13
    assert bucket["best_elo"] == 1011
    assert bucket["top10_avg_elo"] == 1006.5


def test_temporal_scaling_curve_handles_empty_and_unrated_runs() -> None:
    assert temporal_scaling_curve([]) == []
    curve = temporal_scaling_curve([_hyp("a", 1.0, None), _hyp("b", 2.0, None)])
    assert [b["best_elo"] for b in curve] == [None, None]
    assert [b["top10_avg_elo"] for b in curve] == [None, None]


def test_ablation_summary_counts_only_fully_paired_goals() -> None:
    def record(goal: str, arm: str, quality: float) -> dict[str, Any]:
        return {
            "goal_id": goal,
            "arm": arm,
            "expert_quality": quality,
            "diversity": 0.7,
            "verified_claim_ratio": 0.5,
            "cost_usd": 1.0,
            "latency_seconds": 10.0,
        }

    summary = ablation_summary(
        [
            record("g1", "baseline", 3.0),
            record("g1", "no_debate", 2.0),
            record("g2", "baseline", 4.0),
        ]
    )

    assert summary["paired_goal_count"] == 1
    assert summary["arms"]["baseline"]["expert_quality"] == 3.5
    assert summary["arms"]["no_debate"]["n"] == 1


_STRICT_ITEM = {
    "id": "strict-test-item",
    "question": "test question",
    "candidates": [
        {"id": "a", "text": "best", "correctness": 3},
        {"id": "b", "text": "good", "correctness": 2},
        {"id": "c", "text": "bad", "correctness": 1},
        {"id": "d", "text": "worst", "correctness": 0},
    ],
}


def test_comparators_recover_or_invert_a_strict_ranking() -> None:
    preferring = evaluate_concordance(
        [_STRICT_ITEM], correctness_preferring_comparator, "preferring"
    )
    inverting = evaluate_concordance([_STRICT_ITEM], inverting_comparator, "inverting")
    assert (preferring["mean_tau_b"], preferring["top1_accuracy"]) == (1.0, 1.0)
    assert (inverting["mean_tau_b"], inverting["top1_accuracy"]) == (-1.0, 0.0)


def test_coin_flip_comparator_is_seeded_deterministically() -> None:
    runs = [
        evaluate_concordance([_STRICT_ITEM], make_coin_flip_comparator(7), "coin_flip")
        for _ in range(2)
    ]
    assert runs[0] == runs[1]


def test_elo_bucket_accuracy_pools_across_items_in_50_point_increments() -> None:
    per_item: list[dict[str, Any]] = [
        {"ratings": {"a": 1210, "b": 1190}, "correctness": {"a": 3, "b": 1}},
        {"ratings": {"c": 1150, "d": 1100}, "correctness": {"c": 3, "d": 0}},
        {"ratings": {}, "correctness": {}},
    ]
    buckets = elo_bucket_accuracy(per_item)
    assert [(b["bucket"], b["accuracy"]) for b in buckets] == [
        ("1051-1100", 0.0),
        ("1101-1150", 1.0),
        ("1151-1200", 0.0),
        ("1201-1250", 1.0),
    ]
    assert elo_bucket_accuracy([]) == []


def test_committed_dataset_has_ground_truth_and_scores_comparators() -> None:
    items = _load_dataset()["items"]
    assert len(items) >= 5
    for item in items:
        scores = [c["correctness"] for c in item["candidates"]]
        assert len(scores) >= 3, item["id"]
        assert 3 in scores and 0 in scores, item["id"]
        assert len({c["id"] for c in item["candidates"]}) == len(scores)

    preferring = evaluate_concordance(items, correctness_preferring_comparator, "preferring")
    inverting = evaluate_concordance(items, inverting_comparator, "inverting")
    assert preferring["mean_tau_b"] > 0.8
    assert preferring["top1_accuracy"] == 1.0
    up = [b["accuracy"] for b in preferring["elo_buckets"]]
    down = [b["accuracy"] for b in inverting["elo_buckets"]]
    assert len(up) >= 2 and up == sorted(up) and up[-1] > up[0]
    assert down == sorted(down, reverse=True)
