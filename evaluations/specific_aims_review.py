"""The fifteen-axis pilot measures agreement, not scientific quality.

Keep its axes and scale separate from expert and engine review scores.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from evaluations.expert_review import (
    ExpertReviewValidationError,
    _item_id,
    _validate_ids,
)

SPECIFIC_AIMS_SCHEMA_VERSION = 1

SPECIFIC_AIMS_DOMAINS: dict[str, tuple[str, ...]] = {
    "significance_and_innovation": (
        "unmet_clinical_needs",
        "bridges_therapeutic_gap",
        "scientifically_rigorous_rationale",
        "integrates_prior_studies",
        "avoids_over_extrapolation",
    ),
    "rigor_and_feasibility": (
        "clear_hypotheses_and_methods",
        "clearly_stated_aims",
        "path_to_clinical_application",
        "well_defined_endpoints",
        "meaningful_preclinical_experiments",
        "translational_component",
        "avoids_inaccuracies",
        "evidence_based_assumptions",
        "originality_and_terminology",
        "clear_writing_and_organization",
    ),
}

SPECIFIC_AIMS_AXES: tuple[str, ...] = (
    SPECIFIC_AIMS_DOMAINS["significance_and_innovation"]
    + SPECIFIC_AIMS_DOMAINS["rigor_and_feasibility"]
)

# Ascending order, as published. This is the AGREEMENT scale -- never zip
# or compare it positionally against RATING_AXES' 1-5 quality ints.
AGREEMENT_SCALE: tuple[str, ...] = (
    "strongly_disagree",
    "disagree",
    "neutral",
    "agree",
    "strongly_agree",
)


def build_specific_aims_export(
    run_id: str, hypotheses: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build a blinded Specific-Aims-rubric export.

    Same blinding contract as ``expert_review.build_blinded_export``: strips
    provider/Elo/lineage, keeps only the opaque item id and the text a rater
    needs. Uses the 15-axis agreement instrument, never ``RATING_AXES``.

    Args:
        run_id: The run the hypotheses belong to (hashed into the item id).
        hypotheses: Serialized hypotheses (need ``id`` and ``text``).

    Returns:
        A machine-readable blinded export naming its own instrument.
    """
    return {
        "schema_version": SPECIFIC_AIMS_SCHEMA_VERSION,
        "instrument": "specific_aims_rubric_v1",
        "domains": {
            domain: list(axes) for domain, axes in SPECIFIC_AIMS_DOMAINS.items()
        },
        "axes": list(SPECIFIC_AIMS_AXES),
        "agreement_scale": list(AGREEMENT_SCALE),
        "items": [
            {
                "item_id": _item_id(run_id, str(h["id"])),
                "text": str(h.get("text", "")),
            }
            for h in hypotheses
        ],
    }


@dataclasses.dataclass(frozen=True)
class SpecificAimsRating:
    """One rater's 15-axis agreement rating of one blinded item."""

    rater_id: str
    item_id: str
    ratings: dict[str, str]


def _validate_specific_aims_axes(raw: dict[str, Any]) -> dict[str, str]:
    """Validate that every one of the 15 axes holds an agreement-scale label.

    Args:
        raw: One raw rating dict; ``raw["ratings"]`` must map every axis in
            ``SPECIFIC_AIMS_AXES`` to a value in ``AGREEMENT_SCALE``.

    Returns:
        The validated axis-to-label mapping.

    Raises:
        ExpertReviewValidationError: If ``ratings`` is missing, not an
            object, or any axis is missing/out of the agreement scale.
    """
    ratings = raw.get("ratings")
    if not isinstance(ratings, dict):
        raise ExpertReviewValidationError("ratings must be an object")
    parsed: dict[str, str] = {}
    for axis in SPECIFIC_AIMS_AXES:
        value = ratings.get(axis)
        if value not in AGREEMENT_SCALE:
            raise ExpertReviewValidationError(
                f"{axis} must be one of {AGREEMENT_SCALE}, got {value!r}"
            )
        parsed[axis] = value
    return parsed


def parse_specific_aims_ratings(
    payload: dict[str, Any],
) -> list[SpecificAimsRating]:
    """Validate and parse an imported Specific-Aims ratings payload.

    Every one of the 15 axes must be present and hold one of the five
    agreement labels; a malformed rating fails closed rather than being
    silently coerced. Mirrors ``expert_review.parse_ratings``' contract, on
    the separate instrument.

    Args:
        payload: ``{"schema_version": int, "ratings": [ {...}, ... ]}``.

    Returns:
        The validated ratings.

    Raises:
        ExpertReviewValidationError: On any schema violation.
    """
    if payload.get("schema_version") != SPECIFIC_AIMS_SCHEMA_VERSION:
        raise ExpertReviewValidationError(
            f"unsupported schema_version {payload.get('schema_version')!r}"
        )
    ratings: list[SpecificAimsRating] = []
    seen: set[tuple[str, str]] = set()
    for raw in payload.get("ratings", []):
        rater_id, item_id = _validate_ids(raw)
        identity = (rater_id, item_id)
        if identity in seen:
            raise ExpertReviewValidationError(
                f"duplicate rating for rater/item {identity!r}"
            )
        seen.add(identity)
        ratings.append(
            SpecificAimsRating(
                rater_id=rater_id,
                item_id=item_id,
                ratings=_validate_specific_aims_axes(raw),
            )
        )
    return ratings


def summarize_specific_aims_ratings(
    ratings: list[SpecificAimsRating],
) -> dict[str, Any]:
    """Summarize a Specific-Aims panel as a per-axis agreement distribution.

    Deliberately NOT a mean/confidence-interval (unlike
    ``expert_review.summarize_ratings``): this is an ordinal agreement
    scale, not a cardinal quality score, so no numeric average is computed
    here. No threshold is applied and nothing is compared against the two
    published exemplars -- they are a reference distribution, not a
    calibration set (see ``evaluations/datasets/specific_aims_rubric_v1.json``).

    Args:
        ratings: Validated ratings from ``parse_specific_aims_ratings``.

    Returns:
        Panel size plus, for every axis, a count of ratings at each of the
        five agreement levels.
    """
    counts: dict[str, dict[str, int]] = {
        axis: dict.fromkeys(AGREEMENT_SCALE, 0) for axis in SPECIFIC_AIMS_AXES
    }
    for rating in ratings:
        for axis, value in rating.ratings.items():
            counts[axis][value] += 1
    return {
        "schema_version": SPECIFIC_AIMS_SCHEMA_VERSION,
        "panel": {
            "rater_count": len({rating.rater_id for rating in ratings}),
            "item_count": len({rating.item_id for rating in ratings}),
            "rating_count": len(ratings),
        },
        "axis_distribution": counts,
    }
