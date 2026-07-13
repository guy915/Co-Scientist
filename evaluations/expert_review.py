"""Blinded expert-review export/import schema (PLAN.md Milestone 8).

Google's evaluation had biomedical experts rate outputs on scientific quality
and preference. Reproducing those *ratings* needs a recruited expert panel and
is an external gap. What is tractable and required is the *schema*: a blinded
export of hypotheses for experts to rate on every required quality axis, and a
validating import so results are machine-readable across equivalent budgets.

Blinding: the export strips run/provider/Elo so a rater cannot infer which
system produced a hypothesis; a stable opaque ``item_id`` links a rating back on
import. No ratings are fabricated here — this module only defines and validates
the round-trip.
"""

from __future__ import annotations

import dataclasses
import hashlib
from typing import Any

SCHEMA_VERSION = 2

# The 1-5 axes and 1-N preference rank the export asks experts to fill. Impact
# is retained alongside the five acceptance-condition axes used by the system.
RATING_AXES = (
    "alignment",
    "plausibility",
    "novelty",
    "testability",
    "safety",
    "impact",
)


def _item_id(run_id: str, hypothesis_id: str) -> str:
    """Return a stable opaque id that does not leak the source system."""
    digest = hashlib.sha256(f"{run_id}:{hypothesis_id}".encode()).hexdigest()
    return f"item-{digest[:16]}"


def build_blinded_export(
    run_id: str, hypotheses: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build a blinded expert-review export from a run's hypotheses.

    Strips provider/Elo/lineage so raters cannot infer the source system; keeps
    only the opaque item id and the text an expert needs to rate.

    Args:
        run_id: The run the hypotheses belong to (hashed into the item id).
        hypotheses: Serialized hypotheses (need ``id`` and ``text``).

    Returns:
        A machine-readable blinded export.
    """
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
    """One expert's rating of one item, validated on import."""

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


def parse_ratings(payload: dict[str, Any]) -> list[ExpertRating]:
    """Validate and parse an imported expert-ratings payload.

    Each axis must be an integer in 1-5 and the preference rank a positive
    integer. A malformed rating fails closed rather than being silently
    coerced, so no invalid rating enters the results.

    Args:
        payload: ``{"schema_version": int, "ratings": [ {...}, ... ]}``.

    Returns:
        The validated ratings.

    Raises:
        ExpertReviewValidationError: On any schema violation.
    """
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ExpertReviewValidationError(
            f"unsupported schema_version {payload.get('schema_version')!r}"
        )
    ratings: list[ExpertRating] = []
    for raw in payload.get("ratings", []):
        for axis in RATING_AXES:
            value = raw.get(axis)
            if not isinstance(value, int) or not 1 <= value <= 5:
                raise ExpertReviewValidationError(
                    f"{axis} must be an integer in 1-5, got {value!r}"
                )
        rank = raw.get("preference_rank")
        if not isinstance(rank, int) or rank < 1:
            raise ExpertReviewValidationError(
                f"preference_rank must be a positive integer, got {rank!r}"
            )
        if not raw.get("item_id"):
            raise ExpertReviewValidationError("missing item_id")
        ratings.append(
            ExpertRating(
                item_id=str(raw["item_id"]),
                alignment=raw["alignment"],
                plausibility=raw["plausibility"],
                novelty=raw["novelty"],
                testability=raw["testability"],
                safety=raw["safety"],
                impact=raw["impact"],
                preference_rank=rank,
            )
        )
    return ratings
