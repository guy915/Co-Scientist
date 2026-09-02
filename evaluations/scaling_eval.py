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
  even offline: a hypothesis's ``generation`` (0 for an originally
  generated hypothesis, N for an evolution descendant N rounds removed)
  is a genuine cycle ordinal the engine assigns, not a byproduct of
  comparing identical canned answers across tiers. It is coarser than the
  paper's own continuous wall-clock partition, though: our schema carries
  no per-hypothesis authorship timestamp, only an INSERT-time
  ``created_at`` that lands one generation call's whole batch of siblings
  within a fraction of a millisecond of each other (confirmed against a
  real run), and our runs cap at a handful of generation values rather
  than the paper's long-running multi-hour loop -- see
  ``_temporal_order_key`` for exactly what is and is not ordered.
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


def _temporal_order_key(item: dict[str, Any]) -> tuple[int, float, str]:
    """Sort key approximating a hypothesis's place in a run's timeline.

    Ordered primarily by ``generation`` -- the engine's own lineage
    ordinal (0 for an originally generated hypothesis; ``evolve_results.py``
    assigns a child ``parent.generation + 1``, so it strictly increases
    each time a descendant survives another evolution round). This is the
    only real cycle signal in the persisted schema: the engine's
    ``Hypothesis`` model carries no timestamp of its own (nothing to read
    before the drain's own INSERT), so ``created_at`` cannot distinguish
    hypotheses within one generation call's batch -- confirmed against a
    real offline run, where an entire ~13-hypothesis generation call
    landed within under a millisecond of itself. ``created_at`` therefore
    only breaks ties *within* a generation, as batch-insert order, not as
    a claim about which hypothesis was "thought of" first; ``id`` breaks
    any still-remaining tie deterministically. A hypothesis missing
    either field sorts first on that key rather than raising, since some
    callers (tests, older snapshots) may omit them.
    """
    generation = item.get("generation")
    created_at = item.get("created_at")
    return (
        int(generation) if generation is not None else 0,
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
