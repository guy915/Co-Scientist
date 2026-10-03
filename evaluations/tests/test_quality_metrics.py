"""Quality metrics regression tests."""

from __future__ import annotations

from typing import Any

from evaluations.elo_concordance_eval import (
    Candidate,
    _load_dataset,
    correctness_preferring_comparator,
    elo_bucket_accuracy,
    evaluate_concordance,
    inverting_comparator,
    kendall_tau_b,
    make_coin_flip_comparator,
)
from evaluations.metrics import (
    generation_vs_evolution_yield,
    hypothesis_diversity,
)
from evaluations.scaling_eval import (
    ablation_summary,
    scaling_curve,
    temporal_scaling_curve,
)

# Metrics.


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


# Scaling eval.


def _hyp(
    hid: str,
    created_at: float,
    elo: int | None,
    generation: int = 0,
    creation_iteration: int | None = None,
) -> dict[str, Any]:
    """Build one bare hypothesis dict for the temporal-bucket tests.

    ``creation_iteration`` is omitted from the row entirely when None, so a
    test can exercise the legacy fallback (order by ``generation``) simply by
    not passing it.
    """
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


def test_temporal_scaling_curve_falls_back_to_generation_when_no_cycle() -> (
    None
):
    """Legacy rows without ``creation_iteration`` order by ``generation``.

    A row predating the ``creation_iteration`` column carries no cycle
    ordinal, so the timeline key falls back to lineage depth -- reproducing
    the historical generation-primary order exactly. ``early`` has the
    smallest ``created_at`` but the highest generation (an evolution
    descendant two rounds removed); a bug that ordered by ``created_at`` or
    list position instead would put it first, not last.
    """
    hypotheses = [
        _hyp("late", created_at=30.0, elo=1100, generation=0),
        _hyp("early", created_at=1.0, elo=1300, generation=2),
        _hyp("mid", created_at=20.0, elo=1200, generation=1),
    ]

    curve = temporal_scaling_curve(hypotheses, bucket_count=3)

    assert [b["best_elo"] for b in curve] == [1100, 1200, 1300]
    assert [b["n_hypotheses"] for b in curve] == [1, 1, 1]
    assert [b["bucket"] for b in curve] == [1, 2, 3]
    assert all(b["of"] == 3 for b in curve)


def test_temporal_scaling_curve_orders_primarily_by_creation_iteration() -> (
    None
):
    """``creation_iteration`` (authoring cycle) overrides ``generation``.

    This corrects a real mis-ordering: when ``generate`` runs again in a
    later cycle, its fresh generation-0 hypotheses must not sort ahead of an
    earlier cycle's evolved (higher-generation) descendants. Here ``reborn``
    is a cycle-2 generation-0 idea and ``evolved`` a cycle-1 generation-2
    descendant; by lineage alone ``reborn`` (gen 0) would sort first, but by
    authoring cycle it belongs last -- it was thought of later.
    """
    hypotheses = [
        _hyp(
            "seed", created_at=1.0, elo=1100, generation=0, creation_iteration=0
        ),
        _hyp(
            "evolved",
            created_at=2.0,
            elo=1200,
            generation=2,
            creation_iteration=1,
        ),
        _hyp(
            "reborn",
            created_at=3.0,
            elo=1300,
            generation=0,
            creation_iteration=2,
        ),
    ]

    curve = temporal_scaling_curve(hypotheses, bucket_count=3)

    # Buckets follow authoring cycle 0 -> 1 -> 2, not lineage 0 -> 0 -> 2.
    assert [b["best_elo"] for b in curve] == [1100, 1200, 1300]


def test_temporal_scaling_curve_breaks_generation_ties_by_created_at() -> None:
    """Within one generation, ``created_at`` (then ``id``) breaks ties."""
    hypotheses = [
        _hyp("late", created_at=30.0, elo=1100, generation=0),
        _hyp("early", created_at=10.0, elo=1300, generation=0),
        _hyp("mid", created_at=20.0, elo=1200, generation=0),
    ]

    curve = temporal_scaling_curve(hypotheses, bucket_count=3)

    assert [b["best_elo"] for b in curve] == [1300, 1200, 1100]


def test_temporal_scaling_curve_tracks_top_10_average_within_a_bucket() -> None:
    """``top10_avg_elo`` averages up to 10 hypotheses per bucket, not more."""
    bucket_a = [_hyp(f"a{i}", float(i), 1000 + i) for i in range(12)]
    curve = temporal_scaling_curve(bucket_a, bucket_count=1)

    assert curve[0]["n_hypotheses"] == 12
    assert curve[0]["best_elo"] == 1011
    # Top 10 of {1000..1011} are 1002..1011, averaging 1006.5.
    assert curve[0]["top10_avg_elo"] == 1006.5


def test_temporal_scaling_curve_handles_an_empty_run() -> None:
    assert temporal_scaling_curve([]) == []


def test_temporal_scaling_curve_handles_fewer_than_ten_hypotheses() -> None:
    """One bucket per hypothesis, not ten with mostly-empty buckets."""
    hypotheses = [_hyp("a", 1.0, 1200), _hyp("b", 2.0, 1250)]

    curve = temporal_scaling_curve(hypotheses)

    assert len(curve) == 2
    assert [b["of"] for b in curve] == [2, 2]
    assert [b["n_hypotheses"] for b in curve] == [1, 1]


def test_temporal_scaling_curve_handles_no_elo_yet() -> None:
    """A hypothesis with no elo_rating never crashes max()/mean()."""
    hypotheses = [_hyp("a", 1.0, None), _hyp("b", 2.0, None)]

    curve = temporal_scaling_curve(hypotheses)

    assert all(b["best_elo"] is None for b in curve)
    assert all(b["top10_avg_elo"] is None for b in curve)


def test_temporal_scaling_curve_skips_unrated_hypotheses_within_a_bucket() -> (
    None
):
    """A bucket with a mix of rated/unrated hypotheses ignores the unrated."""
    hypotheses = [_hyp("a", 1.0, 1200), _hyp("b", 2.0, None)]

    curve = temporal_scaling_curve(hypotheses, bucket_count=1)

    assert curve[0]["n_hypotheses"] == 2
    assert curve[0]["best_elo"] == 1200
    assert curve[0]["top10_avg_elo"] == 1200.0


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


# Elo concordance eval.

# A strictly-ranked item (no correctness ties) isolates the harness's own
# math from the committed dataset's realistic tie structure, so the
# perfect/inverted-agreement assertions below can be exact.
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


def test_kendall_tau_b_perfect_agreement() -> None:
    assert kendall_tau_b([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0


def test_kendall_tau_b_perfect_disagreement() -> None:
    assert kendall_tau_b([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0


def test_kendall_tau_b_handles_ties() -> None:
    # x has no ties; y ties its middle two values -- tau must land strictly
    # between the ordered and reversed extremes, not equal either one.
    tau = kendall_tau_b([1, 2, 3, 4], [1, 2, 2, 4])
    assert tau is not None
    assert -1.0 < tau < 1.0


def test_kendall_tau_b_needs_at_least_two_items() -> None:
    assert kendall_tau_b([1], [1]) is None
    assert kendall_tau_b([], []) is None


def test_correctness_preferring_comparator_recovers_strict_ranking() -> None:
    result = evaluate_concordance(
        [_STRICT_ITEM],
        correctness_preferring_comparator,
        "correctness_preferring",
    )
    assert result["mean_tau_b"] == 1.0
    assert result["top1_accuracy"] == 1.0


def test_inverting_comparator_fully_disagrees_on_strict_ranking() -> None:
    result = evaluate_concordance(
        [_STRICT_ITEM], inverting_comparator, "inverting"
    )
    assert result["mean_tau_b"] == -1.0
    assert result["top1_accuracy"] == 0.0


def test_coin_flip_comparator_is_seeded_deterministically() -> None:
    first = evaluate_concordance(
        [_STRICT_ITEM], make_coin_flip_comparator(7), "coin_flip"
    )
    second = evaluate_concordance(
        [_STRICT_ITEM], make_coin_flip_comparator(7), "coin_flip"
    )
    assert first == second


def test_comparator_direction_disagrees_between_preferring_and_inverting() -> (
    None
):
    """Two comparators judging every pair oppositely never rank alike."""

    def opposite(a: Candidate, b: Candidate, question: str) -> str:
        preferred = correctness_preferring_comparator(a, b, question)
        return "b" if preferred == "a" else "a"

    result = evaluate_concordance([_STRICT_ITEM], opposite, "opposite")
    assert result["mean_tau_b"] == -1.0


def test_committed_dataset_has_an_unambiguous_ground_truth_per_item() -> None:
    """Every item names a correct answer and a clearly wrong one."""
    dataset = _load_dataset()
    items = dataset["items"]
    assert len(items) >= 5, "dataset too small to be a meaningful sample"
    for item in items:
        candidates = item["candidates"]
        assert len(candidates) >= 3, item["id"]
        ids = [c["id"] for c in candidates]
        assert len(ids) == len(set(ids)), f"dup candidate id in {item['id']}"
        scores = [c["correctness"] for c in candidates]
        assert all(0 <= s <= 3 for s in scores), item["id"]
        assert 3 in scores, f"{item['id']} names no correct answer"
        assert 0 in scores, f"{item['id']} names no clearly wrong answer"


def test_elo_bucket_accuracy_pools_across_items_in_50_point_increments() -> (
    None
):
    """Google's published method (SSR L141): 1001-1050, 1051-1100, ...

    Four responses land in four distinct 50-point buckets pooled across two
    items; each bucket's accuracy is the fraction of that bucket's
    responses matching their own item's best correctness.
    """
    per_item = [
        {
            "ratings": {"a": 1210, "b": 1190},
            "correctness": {"a": 3, "b": 1},
        },
        {
            "ratings": {"c": 1150, "d": 1100},
            "correctness": {"c": 3, "d": 0},
        },
    ]
    buckets = elo_bucket_accuracy(per_item)
    assert buckets == [
        {
            "bucket": "1051-1100",
            "floor": 1051,
            "n_responses": 1,
            "accuracy": 0.0,
        },
        {
            "bucket": "1101-1150",
            "floor": 1101,
            "n_responses": 1,
            "accuracy": 1.0,
        },
        {
            "bucket": "1151-1200",
            "floor": 1151,
            "n_responses": 1,
            "accuracy": 0.0,
        },
        {
            "bucket": "1201-1250",
            "floor": 1201,
            "n_responses": 1,
            "accuracy": 1.0,
        },
    ]


def test_elo_bucket_accuracy_handles_no_items() -> None:
    assert elo_bucket_accuracy([]) == []


def test_elo_bucket_accuracy_skips_items_with_no_candidates() -> None:
    """An item with an empty correctness map must not raise on ``max()``."""
    assert elo_bucket_accuracy([{"ratings": {}, "correctness": {}}]) == []


def test_committed_dataset_bucket_accuracy_tracks_comparator_quality() -> None:
    """Bucket accuracy rises with Elo for a ground-truth-agreeing comparator.

    Mirrors the paper's own finding (higher Elo buckets are more often
    correct): a comparator that always prefers the more-correct candidate
    pushes correct answers into higher buckets, so accuracy should be
    non-decreasing in the bucket floor. An always-wrong comparator inverts
    that: accuracy should be non-increasing.
    """
    dataset = _load_dataset()
    preferring = evaluate_concordance(
        dataset["items"],
        correctness_preferring_comparator,
        "correctness_preferring",
    )
    inverting = evaluate_concordance(
        dataset["items"], inverting_comparator, "inverting"
    )
    preferring_accuracies = [b["accuracy"] for b in preferring["elo_buckets"]]
    inverting_accuracies = [b["accuracy"] for b in inverting["elo_buckets"]]
    assert len(preferring_accuracies) >= 2
    assert preferring_accuracies == sorted(preferring_accuracies)
    assert inverting_accuracies == sorted(inverting_accuracies, reverse=True)
    assert preferring_accuracies[-1] > preferring_accuracies[0]


def test_committed_dataset_correctness_preferring_beats_chance() -> None:
    """The real Elo mechanism recovers the dataset's known correctness order.

    This is the harness's own sanity floor, not a claim about the real
    model: the comparator here always agrees with the ground truth, so this
    only proves the Elo/tau plumbing over the actual committed dataset
    (including its realistic correctness ties) behaves as expected.
    """
    dataset = _load_dataset()
    result = evaluate_concordance(
        dataset["items"],
        correctness_preferring_comparator,
        "correctness_preferring",
    )
    assert result["mean_tau_b"] is not None
    assert result["mean_tau_b"] > 0.8
    assert result["top1_accuracy"] == 1.0
