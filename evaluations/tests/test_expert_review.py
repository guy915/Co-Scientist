"""Tests for the blinded expert-review export/import schema (Milestone 8)."""

from __future__ import annotations

import pytest

from evaluations.expert_review import (
    RATING_AXES,
    SCHEMA_VERSION,
    ExpertReviewValidationError,
    build_blinded_export,
    parse_ratings,
)


def test_export_is_blinded() -> None:
    """The export strips provider/Elo/lineage and uses opaque item ids."""
    export = build_blinded_export(
        "run-123",
        [
            {"id": "h1", "text": "idea one", "elo_rating": 1400, "origin": "x"},
            {"id": "h2", "text": "idea two", "elo_rating": 900},
        ],
    )
    assert export["schema_version"] == SCHEMA_VERSION
    assert export["rating_axes"] == list(RATING_AXES)
    for item in export["items"]:
        assert item["item_id"].startswith("item-")
        assert set(item) == {"item_id", "text"}  # no elo/origin/run leaked


def test_stable_item_ids() -> None:
    """The same (run, hypothesis) always maps to the same opaque id."""
    a = build_blinded_export("run", [{"id": "h", "text": "t"}])
    b = build_blinded_export("run", [{"id": "h", "text": "t"}])
    assert a["items"][0]["item_id"] == b["items"][0]["item_id"]


def test_parse_valid_ratings() -> None:
    """Valid ratings parse into structured records."""
    ratings = parse_ratings(
        {
            "schema_version": SCHEMA_VERSION,
            "ratings": [
                {
                    "item_id": "item-abc",
                    "alignment": 5,
                    "novelty": 4,
                    "plausibility": 3,
                    "testability": 4,
                    "safety": 5,
                    "impact": 5,
                    "preference_rank": 1,
                }
            ],
        }
    )
    assert len(ratings) == 1
    assert ratings[0].alignment == 5
    assert ratings[0].novelty == 4
    assert ratings[0].testability == 4
    assert ratings[0].safety == 5
    assert ratings[0].preference_rank == 1


def test_out_of_range_axis_fails_closed() -> None:
    """An axis outside 1-5 raises rather than being coerced."""
    with pytest.raises(ExpertReviewValidationError):
        parse_ratings(
            {
                "schema_version": SCHEMA_VERSION,
                "ratings": [
                    {
                        "item_id": "x",
                        "alignment": 3,
                        "novelty": 9,
                        "plausibility": 3,
                        "testability": 3,
                        "safety": 3,
                        "impact": 3,
                        "preference_rank": 1,
                    }
                ],
            }
        )


def test_missing_required_axis_fails_closed() -> None:
    """A legacy three-axis rating cannot pass as the complete evaluation."""
    with pytest.raises(ExpertReviewValidationError, match="alignment"):
        parse_ratings(
            {
                "schema_version": SCHEMA_VERSION,
                "ratings": [
                    {
                        "item_id": "legacy",
                        "novelty": 4,
                        "plausibility": 4,
                        "impact": 4,
                        "preference_rank": 1,
                    }
                ],
            }
        )


def test_wrong_schema_version_fails_closed() -> None:
    """An unsupported schema version raises."""
    with pytest.raises(ExpertReviewValidationError):
        parse_ratings({"schema_version": 999, "ratings": []})
