"""Elo-vs-known-correctness concordance harness tests."""

from __future__ import annotations

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


def test_committed_dataset_bucket_accuracy_tracks_comparator_quality() -> (
    None
):
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
