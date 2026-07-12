"""Offline test-time scaling and controlled-ablation evaluation."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from evaluations.metrics import hypothesis_diversity


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


def scaling_curve(snapshots: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute quality, diversity, grounding, cost, and latency by budget.

    Each snapshot must represent the same goal/configuration family at one
    committed compute budget. Elo is reported as an internal tournament signal,
    never treated as external quality ground truth; blinded ``expert_score`` is
    the independent quality field when available.
    """
    points = []
    for snapshot in snapshots:
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
        points.append(
            {
                "run_id": snapshot.get("run_id"),
                "goal_id": snapshot.get("goal_id"),
                "compute": {
                    "llm_calls": int(metrics.get("llm_calls", 0)),
                    "tasks": int(metrics.get("tasks", 0)),
                },
                "best_elo": (
                    int(ranked[0].get("elo_rating", 0)) if ranked else None
                ),
                "top10_expert_quality": _mean(expert_scores),
                "top10_diversity": hypothesis_diversity(
                    [_text(item) for item in top]
                ),
                "verified_claim_ratio": _verified_ratio(top),
                "cost_usd": metrics.get("cost_usd"),
                "latency_seconds": metrics.get("latency_seconds"),
                "hypothesis_count": len(hypotheses),
            }
        )
    return sorted(
        points,
        key=lambda item: (
            item["compute"]["llm_calls"],
            item["compute"]["tasks"],
        ),
    )


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
