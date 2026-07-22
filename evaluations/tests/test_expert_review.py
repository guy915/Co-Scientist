"""Tests for the blinded expert-review export/import schema (Milestone 8)."""

from __future__ import annotations

import pytest

from evaluations.expert_review import (
    RATING_AXES,
    SCHEMA_VERSION,
    ExpertReviewValidationError,
    build_blinded_export,
    parse_ratings,
    summarize_ratings,
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
                    "rater_id": "expert-1",
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
    assert ratings[0].rater_id == "expert-1"
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
                        "rater_id": "expert-1",
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
                        "rater_id": "expert-1",
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


_TWO_EXPERT_PANEL = {
    "schema_version": SCHEMA_VERSION,
    "ratings": [
        {
            "rater_id": "expert-1",
            "item_id": "item-a",
            "alignment": 5,
            "plausibility": 4,
            "novelty": 3,
            "testability": 5,
            "safety": 5,
            "impact": 4,
            "preference_rank": 1,
        },
        {
            "rater_id": "expert-2",
            "item_id": "item-a",
            "alignment": 4,
            "plausibility": 4,
            "novelty": 3,
            "testability": 4,
            "safety": 5,
            "impact": 3,
            "preference_rank": 1,
        },
    ],
}


def test_panel_summary_reports_confidence_and_agreement() -> None:
    """Real panel imports produce uncertainty and agreement statistics."""
    ratings = parse_ratings(_TWO_EXPERT_PANEL)

    summary = summarize_ratings(ratings)

    assert summary["panel"] == {
        "rater_count": 2,
        "item_count": 1,
        "rating_count": 2,
    }
    assert summary["axes"]["alignment"]["mean"] == 4.5
    assert len(summary["axes"]["alignment"]["confidence_interval_95"]) == 2
    agreement = summary["inter_rater_agreement"]
    assert agreement["pairwise_comparisons"] == len(RATING_AXES)
    assert agreement["within_one_point"]["proportion"] == 1.0


def test_duplicate_rater_item_fails_closed() -> None:
    """One expert cannot accidentally double-weight an item."""
    row = {
        "rater_id": "expert-1",
        "item_id": "item-a",
        "alignment": 4,
        "plausibility": 4,
        "novelty": 4,
        "testability": 4,
        "safety": 4,
        "impact": 4,
        "preference_rank": 1,
    }
    with pytest.raises(ExpertReviewValidationError, match="duplicate rating"):
        parse_ratings(
            {"schema_version": SCHEMA_VERSION, "ratings": [row, dict(row)]}
        )
