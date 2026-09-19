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
    """Return a rounded mean, or None when no measurements exist."""
    return round(sum(values) / len(values), 4) if values else None


def _text(hypothesis: dict[str, Any]) -> str:
    """Return one hypothesis's canonical proposal text."""
    return str(hypothesis.get("text") or hypothesis.get("statement") or "")


def _verified_ratio(hypotheses: Sequence[dict[str, Any]]) -> float | None:
    """Return verified atomic claims divided by all assessed claims."""
    verified = sum(int(item.get("verified_claims", 0)) for item in hypotheses)
    total = sum(int(item.get("assessed_claims", 0)) for item in hypotheses)
    return round(verified / total, 4) if total else None


def _scaling_point(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build one scaling-curve point from a single run snapshot."""
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
    """Compute quality, diversity, grounding, cost, and latency by budget.

    Each snapshot must represent the same goal/configuration family at one
    committed compute budget. Elo is reported as an internal tournament signal,
    never treated as external quality ground truth; blinded ``expert_score`` is
    the independent quality field when available.
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
    """Return a hypothesis's Elo rating, or None when it carries none."""
    rating = item.get("elo_rating")
    return int(rating) if rating is not None else None


def _temporal_order_key(item: dict[str, Any]) -> tuple[int, int, float, str]:
    """Sort key approximating a hypothesis's place in a run's timeline.

    Ordered primarily by ``creation_iteration`` -- the authoring-cycle
    ordinal the engine stamps at creation (0 for the initial generation, N
    for a research-expansion/evolution cycle N). This is the run's true
    timeline axis, and the closest the persisted schema comes to the paper's
    continuous wall-clock partition (SSR App. D). It is a genuine cycle
    ordinal, not a wall-clock stamp, so it carries signal even offline,
    where every hypothesis is INSERTed at finalize within one sub-second
    drain and ``created_at`` collapses.

    ``generation`` -- the lineage ordinal (0 for an original; a child gets
    ``parent.generation + 1``) -- is the fallback for a legacy row that
    predates the ``creation_iteration`` column, and the secondary key within
    one cycle. Preferring ``creation_iteration`` corrects a real
    mis-ordering: when ``generate`` runs again in a later cycle, its fresh
    generation-0 hypotheses would otherwise sort *ahead* of an earlier
    cycle's evolved (higher-generation) descendants -- the timeline
    backwards. ``created_at`` (the drain's finalize-time INSERT) then breaks
    ties, and ``id`` breaks any still-remaining tie deterministically. A
    hypothesis missing every field sorts first rather than raising, since
    some callers (tests, older snapshots) may omit them; siblings authored
    in one generation call share a cycle and tie down to ``id``, which is
    correct -- they were authored together, with no order to recover.
    """
    creation_iteration = item.get("creation_iteration")
    generation = item.get("generation")
    generation_ordinal = int(generation) if generation is not None else 0
    # creation_iteration is the timeline axis; fall back to the lineage
    # ordinal only where the run predates the column (all-NULL), which
    # reproduces the historical generation-primary order exactly.
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
    """Partition items into up to ``bucket_count`` contiguous equal chunks.

    Fewer than ``bucket_count`` items yields one hypothesis per bucket
    instead of padding out empty ones -- a run with, say, 4 hypotheses
    cannot form 10 *equal, non-empty* temporal buckets, and an empty
    bucket would report a meaningless null point on the curve. Otherwise
    this is the standard near-equal contiguous partition: the first
    ``n % bucket_count`` buckets get one extra item.
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
    """Summarize one temporal bucket's best Elo and top-10-average Elo."""
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
    """Google's published within-run scaling method (SSR L141, Figs. 4-5).

    Partitions ONE run's hypotheses into ``bucket_count`` (default 10)
    equal-size temporal buckets ordered by generation cycle (see
    ``_temporal_order_key``) -- the first bucket the earliest cycle, the
    last the most recent -- and reports each bucket's best (maximum) Elo
    rating and its top-10-average Elo rating (mean of up to the bucket's
    own top 10 ratings, matching the paper's "average Elo rating of the
    top 10 hypotheses" and the same up-to-10 pattern ``_scaling_point``
    already uses for a whole run). Unlike ``scaling_curve`` (separate runs,
    different compute tiers), this never varies budget: it measures
    whether one run's own hypothesis quality trends upward over its own
    generation/evolution cycles -- exactly what Figures 4 and 5 plot, per
    goal, before any cross-goal averaging.

    Resolution caveat: the paper partitions a long-running, continuous
    generation process by wall-clock time; our schema's only real cycle
    signal is the discrete ``generation`` ordinal, and a run caps at a
    handful of generation values (an offline express/standard run reaches
    only 0 and 1 -- one evolution round). Ten buckets over a small
    generation range means several buckets typically share a generation
    and differ only by the coarser, less meaningful ``created_at``/``id``
    tie-break within it -- the curve is real but coarser than the paper's.

    Degenerate cases handled without raising:
        - An empty run (no hypotheses) returns ``[]``.
        - A run with fewer than ``bucket_count`` hypotheses returns one
          bucket per hypothesis rather than padding out empty buckets.
        - A hypothesis with no Elo yet (missing or None ``elo_rating``) is
          excluded from its bucket's Elo stats; a bucket where every
          hypothesis lacks one reports ``best_elo``/``top10_avg_elo`` as
          ``None`` instead of raising.
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
    """Aggregate paired controlled runs by feature arm and metric."""
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
    """Count goals represented in every ablation arm."""
    arms = {str(item.get("arm")) for item in records}
    by_goal: dict[str, set[str]] = defaultdict(set)
    for item in records:
        by_goal[str(item.get("goal_id"))].add(str(item.get("arm")))
    return sum(seen == arms for seen in by_goal.values())


def main() -> int:
    """Evaluate a JSON artifact containing snapshots and/or ablation runs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.artifact.read_text())
    result = {
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
