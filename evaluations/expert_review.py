"""Blind provider, run and Elo identity; quality ratings stay separate from
Specific Aims agreement.
"""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
import math
import statistics
from collections import defaultdict
from typing import Any

SCHEMA_VERSION = 3

# Quality axes include impact alongside the system acceptance axes.
RATING_AXES = (
    "alignment",
    "plausibility",
    "novelty",
    "testability",
    "safety",
    "impact",
)


def _item_id(run_id: str, hypothesis_id: str) -> str:
    digest = hashlib.sha256(f"{run_id}:{hypothesis_id}".encode()).hexdigest()
    return f"item-{digest[:16]}"


def build_blinded_export(run_id: str, hypotheses: list[dict[str, Any]]) -> dict[str, Any]:
    """Remove provider/Elo/lineage so raters cannot infer the source system."""
    return {
        "schema_version": SCHEMA_VERSION,
        "rating_axes": list(RATING_AXES),
        "items": [
            {
                "item_id": _item_id(run_id, str(h["id"])),
                "text": str(h.get("text", "")),
            }
            for h in hypotheses
        ],
    }


@dataclasses.dataclass(frozen=True)
class ExpertRating:
    rater_id: str
    item_id: str
    alignment: int
    plausibility: int
    novelty: int
    testability: int
    safety: int
    impact: int
    preference_rank: int


class ExpertReviewValidationError(Exception):
    """Raised when an imported rating violates the schema."""


def _validate_axes(raw: dict[str, Any]) -> None:
    for axis in RATING_AXES:
        value = raw.get(axis)
        if not isinstance(value, int) or not 1 <= value <= 5:
            raise ExpertReviewValidationError(f"{axis} must be an integer in 1-5, got {value!r}")


def _validate_ids(raw: dict[str, Any]) -> tuple[str, str]:
    rater_id = str(raw.get("rater_id") or "")
    item_id = str(raw.get("item_id") or "")
    if not rater_id:
        raise ExpertReviewValidationError("missing rater_id")
    if not item_id:
        raise ExpertReviewValidationError("missing item_id")
    return rater_id, item_id


def _parse_one_rating(raw: dict[str, Any]) -> ExpertRating:
    rater_id, item_id = _validate_ids(raw)
    _validate_axes(raw)
    rank = raw.get("preference_rank")
    if not isinstance(rank, int) or rank < 1:
        raise ExpertReviewValidationError(
            f"preference_rank must be a positive integer, got {rank!r}"
        )
    return ExpertRating(
        rater_id=rater_id,
        item_id=item_id,
        alignment=raw["alignment"],
        plausibility=raw["plausibility"],
        novelty=raw["novelty"],
        testability=raw["testability"],
        safety=raw["safety"],
        impact=raw["impact"],
        preference_rank=rank,
    )


def parse_ratings(payload: dict[str, Any]) -> list[ExpertRating]:
    """Malformed panel ratings fail closed rather than silently entering
    measurements.
    """
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ExpertReviewValidationError(
            f"unsupported schema_version {payload.get('schema_version')!r}"
        )
    ratings: list[ExpertRating] = []
    seen: set[tuple[str, str]] = set()
    for raw in payload.get("ratings", []):
        rating = _parse_one_rating(raw)
        identity = (rating.rater_id, rating.item_id)
        if identity in seen:
            raise ExpertReviewValidationError(f"duplicate rating for rater/item {identity!r}")
        seen.add(identity)
        ratings.append(rating)
    return ratings


def _mean_confidence_interval(values: list[int]) -> dict[str, Any]:
    mean = statistics.fmean(values)
    margin = 1.96 * statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return {
        "mean": round(mean, 4),
        "confidence_interval_95": [
            round(max(1.0, mean - margin), 4),
            round(min(5.0, mean + margin), 4),
        ],
        "n": len(values),
    }


def _wilson_interval(successes: int, total: int) -> list[float] | None:
    if total == 0:
        return None
    z = 1.96
    proportion = successes / total
    denominator = 1 + z**2 / total
    centre = (proportion + z**2 / (2 * total)) / denominator
    margin = (
        z * math.sqrt(proportion * (1 - proportion) / total + z**2 / (4 * total**2)) / denominator
    )
    return [round(centre - margin, 4), round(centre + margin, 4)]


def _pairwise_agreement(
    co_ratings: dict[tuple[str, str], list[int]],
) -> dict[str, Any]:
    exact = 0
    within_one = 0
    comparisons = 0
    for values in co_ratings.values():
        for left, right in itertools.combinations(values, 2):
            comparisons += 1
            exact += int(left == right)
            within_one += int(abs(left - right) <= 1)

    def agreement(successes: int) -> dict[str, Any]:
        return {
            "proportion": (round(successes / comparisons, 4) if comparisons else None),
            "confidence_interval_95": _wilson_interval(successes, comparisons),
        }

    return {
        "pairwise_comparisons": comparisons,
        "exact": agreement(exact),
        "within_one_point": agreement(within_one),
        "method": "pairwise agreement across co-rated item-axis pairs",
    }


def summarize_ratings(ratings: list[ExpertRating]) -> dict[str, Any]:
    """No agreement statistic is meaningful without co-rated items."""
    by_axis: dict[str, list[int]] = {axis: [] for axis in RATING_AXES}
    co_ratings: dict[tuple[str, str], list[int]] = defaultdict(list)
    for rating in ratings:
        for axis in RATING_AXES:
            value = int(getattr(rating, axis))
            by_axis[axis].append(value)
            co_ratings[(rating.item_id, axis)].append(value)

    return {
        "schema_version": SCHEMA_VERSION,
        "panel": {
            "rater_count": len({rating.rater_id for rating in ratings}),
            "item_count": len({rating.item_id for rating in ratings}),
            "rating_count": len(ratings),
        },
        "axes": {
            axis: _mean_confidence_interval(values) if values else None
            for axis, values in by_axis.items()
        },
        "inter_rater_agreement": _pairwise_agreement(co_ratings),
    }
