"""Offline test-time scaling and controlled-ablation evaluation.

Two distinct scaling methods live here, answering different questions --
see each function's docstring for which is which:

- ``scaling_curve`` compares SEPARATE runs at different compute *tiers*.
  Offline, this measures the harness's wiring, not the model: the
  deterministic offline backend answers every call the same canned way
  regardless of tier, so an offline curve cannot show quality scaling with
  budget (see ``EVAL-SCALING-001``'s residual).
- ``temporal_scaling_curve`` is Google's own published method (SSR L141,
  App. D; Figures 4-5): partition ONE run's hypotheses into ten equal
  temporal buckets in generation-cycle order and track best/top-10-average
  Elo across them. It never varies tier -- it measures whether a single
  run's own hypothesis quality trends upward over its own generation/
  evolution cycles. Unlike the tier curve, the *ordering signal* is real
  even offline: a hypothesis's ``creation_iteration`` (the authoring-cycle
  ordinal the engine stamps at creation -- 0 for the initial generation, N
  for a research-expansion/evolution cycle N) is a genuine cycle ordinal
  the engine assigns, not a byproduct of comparing identical canned answers
  across tiers. It is the closest the persisted schema comes to the paper's
  own continuous wall-clock partition: the drain's INSERT-time ``created_at``
  cannot substitute, since every hypothesis of a run is written at finalize
  within one sub-second pass (confirmed against real runs) and so carries no
  authoring-timeline signal, and our runs cap at a handful of cycles rather
  than the paper's long-running multi-hour loop. ``generation`` (lineage
  depth) remains the fallback for a row predating the ``creation_iteration``
  column -- see ``_temporal_order_key`` for exactly what is and is not
  ordered.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from evaluations.metrics import hypothesis_diversity

_TEMPORAL_BUCKET_COUNT = 10
_TOP_N_ELO = 10


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _text(hypothesis: dict[str, Any]) -> str:
    return str(hypothesis.get("text") or hypothesis.get("statement") or "")


def _verified_ratio(hypotheses: Sequence[dict[str, Any]]) -> float | None:
    verified = sum(int(item.get("verified_claims", 0)) for item in hypotheses)
    total = sum(int(item.get("assessed_claims", 0)) for item in hypotheses)
    return round(verified / total, 4) if total else None


def _scaling_point(snapshot: dict[str, Any]) -> dict[str, Any]:
    hypotheses = list(snapshot.get("hypotheses") or [])
    ranked = sorted(
        hypotheses,
        key=lambda item: int(item.get("elo_rating", 0)),
        reverse=True,
    )
    top = ranked[:10]
    expert_scores = [
        float(item["expert_score"])
        for item in top
        if item.get("expert_score") is not None
    ]
    metrics = snapshot.get("metrics") or {}
    return {
        "run_id": snapshot.get("run_id"),
        "evaluation_identity": snapshot.get("evaluation_identity"),
        "goal_id": snapshot.get("goal_id"),
        "compute": {
            "llm_calls": int(metrics.get("llm_calls", 0)),
            "tasks": int(metrics.get("tasks", 0)),
        },
        "best_elo": (int(ranked[0].get("elo_rating", 0)) if ranked else None),
        "top10_expert_quality": _mean(expert_scores),
        "top10_diversity": hypothesis_diversity([_text(item) for item in top]),
        "verified_claim_ratio": _verified_ratio(top),
        "cost_usd": metrics.get("cost_usd"),
        "cost_basis": "partial_static_estimate",
        "usage_evidence": metrics.get("usage_evidence"),
        "latency_seconds": metrics.get("latency_seconds"),
        "hypothesis_count": len(hypotheses),
    }


def scaling_curve(snapshots: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare the same goal/config family; internal Elo is not external
    quality ground truth.
    """
    points = [_scaling_point(snapshot) for snapshot in snapshots]
    return sorted(
        points,
        key=lambda item: (
            item["compute"]["llm_calls"],
            item["compute"]["tasks"],
        ),
    )


def _hypothesis_elo(item: dict[str, Any]) -> int | None:
    rating = item.get("elo_rating")
    return int(rating) if rating is not None else None


def _temporal_order_key(item: dict[str, Any]) -> tuple[int, int, float, str]:
    """Creation cycles survive batched finalization timestamps; lineage alone
    reverses later fresh generations.
    """
    creation_iteration = item.get("creation_iteration")
    generation = item.get("generation")
    generation_ordinal = int(generation) if generation is not None else 0
    # Use authoring cycles; only legacy all-NULL runs fall back to lineage
    # order.
    timeline = (
        int(creation_iteration)
        if creation_iteration is not None
        else generation_ordinal
    )
    created_at = item.get("created_at")
    return (
        timeline,
        generation_ordinal,
        float(created_at) if created_at is not None else 0.0,
        str(item.get("id") or ""),
    )


def _split_into_buckets(
    items: Sequence[dict[str, Any]], bucket_count: int
) -> list[list[dict[str, Any]]]:
    """Small pools cannot form equal nonempty buckets; do not pad meaningless
    null points.
    """
    n = len(items)
    if n == 0:
        return []
    k = min(bucket_count, n)
    base, remainder = divmod(n, k)
    buckets: list[list[dict[str, Any]]] = []
    start = 0
    for i in range(k):
        size = base + (1 if i < remainder else 0)
        buckets.append(list(items[start : start + size]))
        start += size
    return buckets


def _temporal_bucket_point(
    bucket: Sequence[dict[str, Any]], index: int, total: int
) -> dict[str, Any]:
    ratings = [r for r in (_hypothesis_elo(h) for h in bucket) if r is not None]
    ranked = sorted(ratings, reverse=True)
    return {
        "bucket": index + 1,
        "of": total,
        "n_hypotheses": len(bucket),
        "best_elo": max(ratings) if ratings else None,
        "top10_avg_elo": _mean(ranked[:_TOP_N_ELO]),
    }


def temporal_scaling_curve(
    hypotheses: Sequence[dict[str, Any]],
    *,
    bucket_count: int = _TEMPORAL_BUCKET_COUNT,
) -> list[dict[str, Any]]:
    """Within-run authoring-cycle trends differ from across-run budget
    scaling and are coarser than wall time.
    """
    ordered = sorted(hypotheses, key=_temporal_order_key)
    buckets = _split_into_buckets(ordered, bucket_count)
    return [
        _temporal_bucket_point(bucket, i, len(buckets))
        for i, bucket in enumerate(buckets)
    ]


def _complete_cost_mean(items: Sequence[dict[str, Any]]) -> float | None:
    costs: list[float] = []
    for item in items:
        evidence = item.get("usage_evidence") or {}
        value = evidence.get("estimated_total_usd")
        if not evidence.get("estimate_complete") or value is None:
            return None
        costs.append(float(value))
    return _mean(costs)


def ablation_summary(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get("arm") or "unspecified")].append(record)
    arms: dict[str, Any] = {}
    for arm, items in sorted(grouped.items()):
        arms[arm] = {
            "n": len(items),
            "expert_quality": _mean(
                [
                    float(item["expert_quality"])
                    for item in items
                    if item.get("expert_quality") is not None
                ]
            ),
            "diversity": _mean([float(item["diversity"]) for item in items]),
            "verified_claim_ratio": _mean(
                [
                    float(item["verified_claim_ratio"])
                    for item in items
                    if item.get("verified_claim_ratio") is not None
                ]
            ),
            "cost_usd": _mean([float(item["cost_usd"]) for item in items]),
            "cost_basis": "partial_static_estimate",
            "estimated_mean_usd": _complete_cost_mean(items),
            "latency_seconds": _mean(
                [float(item["latency_seconds"]) for item in items]
            ),
            "goal_ids": sorted({str(item.get("goal_id")) for item in items}),
        }
    return {"arms": arms, "paired_goal_count": _paired_goal_count(records)}


def _paired_goal_count(records: Sequence[dict[str, Any]]) -> int:
    arms = {str(item.get("arm")) for item in records}
    by_goal: dict[str, set[str]] = defaultdict(set)
    for item in records:
        by_goal[str(item.get("goal_id"))].add(str(item.get("arm")))
    return sum(seen == arms for seen in by_goal.values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.artifact.read_text())
    from evaluations._identity import validate_comparison

    validation = {
        "scaling": validate_comparison(
            payload.get("snapshots", []), kind="scaling"
        ),
        "ablation": validate_comparison(
            payload.get("ablations", []), kind="ablation"
        ),
    }
    result = {
        "comparison_validation": validation,
        "scaling_curve": scaling_curve(payload.get("snapshots", [])),
        "ablation": ablation_summary(payload.get("ablations", [])),
        "provenance": {
            "elo_is_quality_ground_truth": False,
            "expert_scores_required_for_quality_claims": True,
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
