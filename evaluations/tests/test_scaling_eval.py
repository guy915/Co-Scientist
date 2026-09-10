"""Scaling-curve and controlled-ablation evaluation tests."""

from __future__ import annotations

from typing import Any

from evaluations.scaling_eval import (
    ablation_summary,
    scaling_curve,
    temporal_scaling_curve,
)


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
