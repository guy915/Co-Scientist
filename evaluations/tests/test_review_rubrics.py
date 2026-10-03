"""Review rubrics regression tests."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from evaluations.expert_review import (
    RATING_AXES,
    SCHEMA_VERSION,
    ExpertReviewValidationError,
    build_blinded_export,
    parse_ratings,
    summarize_ratings,
)
from evaluations.specific_aims_review import (
    AGREEMENT_SCALE,
    SPECIFIC_AIMS_AXES,
    SPECIFIC_AIMS_DOMAINS,
    SPECIFIC_AIMS_SCHEMA_VERSION,
    build_specific_aims_export,
    parse_specific_aims_ratings,
    summarize_specific_aims_ratings,
)

# Expert review.


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


# Specific aims rubric.

_DATASET_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "datasets"
    / "specific_aims_rubric_v1.json"
)


def _load_dataset() -> dict[str, Any]:
    result: dict[str, Any] = json.loads(
        _DATASET_PATH.read_text(encoding="utf-8")
    )
    return result


def _exemplar(dataset: dict[str, Any], case: str) -> dict[str, Any]:
    for exemplar in dataset["exemplars"]:
        if exemplar["case"] == case:
            return exemplar  # type: ignore[no-any-return]
    raise AssertionError(f"no exemplar named {case!r}")


def test_domains_hold_five_and_ten_axes() -> None:
    assert len(SPECIFIC_AIMS_DOMAINS["significance_and_innovation"]) == 5
    assert len(SPECIFIC_AIMS_DOMAINS["rigor_and_feasibility"]) == 10
    assert len(SPECIFIC_AIMS_AXES) == 15
    assert len(set(SPECIFIC_AIMS_AXES)) == 15  # no duplicate axis


def test_dataset_axes_match_the_code_exactly() -> None:
    """The JSON rubric and the code constant must never drift apart."""
    dataset = _load_dataset()
    sig = dataset["rubric"]["domains"]["significance_and_innovation"]
    rig = dataset["rubric"]["domains"]["rigor_and_feasibility"]
    json_axes = tuple(a["axis"] for a in sig) + tuple(a["axis"] for a in rig)
    assert json_axes == SPECIFIC_AIMS_AXES
    assert tuple(dataset["rubric"]["scale"]["levels"]) == AGREEMENT_SCALE


def test_instrument_never_overlaps_the_six_axis_quality_score() -> None:
    """R10-1: a different instrument, never merged with RATING_AXES."""
    assert set(SPECIFIC_AIMS_AXES).isdisjoint(RATING_AXES)
    assert len(RATING_AXES) == 6
    assert len(SPECIFIC_AIMS_AXES) == 15


def test_export_is_blinded_and_names_its_own_instrument() -> None:
    export = build_specific_aims_export(
        "run-1", [{"id": "h1", "text": "idea", "elo_rating": 1400}]
    )
    assert export["schema_version"] == SPECIFIC_AIMS_SCHEMA_VERSION
    assert export["instrument"] == "specific_aims_rubric_v1"
    assert export["axes"] == list(SPECIFIC_AIMS_AXES)
    assert export["agreement_scale"] == list(AGREEMENT_SCALE)
    item = export["items"][0]
    assert set(item) == {"item_id", "text"}  # no elo leaked


def _ratings_payload(item_id: str, ratings: dict[str, str]) -> dict[str, Any]:
    return {
        "schema_version": SPECIFIC_AIMS_SCHEMA_VERSION,
        "ratings": [
            {"rater_id": "rater-1", "item_id": item_id, "ratings": ratings}
        ],
    }


@pytest.mark.parametrize(
    "case", ["lapatinib_colon_cancer", "selinexor_colon_cancer"]
)
def test_published_exemplars_round_trip_to_their_own_counts(case: str) -> None:
    """The two rated exemplars reproduce the paper's published counts."""
    dataset = _load_dataset()
    exemplar = _exemplar(dataset, case)
    payload = _ratings_payload("item-x", exemplar["ratings"])

    parsed = parse_specific_aims_ratings(payload)
    summary = summarize_specific_aims_ratings(parsed)

    distribution = summary["axis_distribution"]
    counts = dict.fromkeys(AGREEMENT_SCALE, 0)
    for axis_counts in distribution.values():
        for level, n in axis_counts.items():
            counts[level] += n
    assert counts == exemplar["published_counts"]


def test_givosiran_exemplar_is_present_with_no_rating_block() -> None:
    """The third worked example is kept, not dropped, with its own note."""
    dataset = _load_dataset()
    givosiran = _exemplar(dataset, "givosiran_aml")
    assert givosiran["ratings"] is None
    assert givosiran.get("absence_note")


def test_malformed_axis_value_fails_closed() -> None:
    bad_ratings = dict.fromkeys(SPECIFIC_AIMS_AXES, "agree")
    bad_ratings["unmet_clinical_needs"] = "somewhat_agree"  # not on the scale
    with pytest.raises(ExpertReviewValidationError):
        parse_specific_aims_ratings(_ratings_payload("item-x", bad_ratings))


def test_missing_axis_fails_closed() -> None:
    incomplete = dict.fromkeys(SPECIFIC_AIMS_AXES[:-1], "agree")  # 14 of 15
    with pytest.raises(ExpertReviewValidationError):
        parse_specific_aims_ratings(_ratings_payload("item-x", incomplete))


def test_summary_never_computes_a_mean_or_a_threshold_verdict() -> None:
    """R10-12/R10-10: agreement scale; exemplars are not a calibration set."""
    full_agree = dict.fromkeys(SPECIFIC_AIMS_AXES, "strongly_agree")
    parsed = parse_specific_aims_ratings(_ratings_payload("item-x", full_agree))
    summary = summarize_specific_aims_ratings(parsed)

    assert set(summary) == {"schema_version", "panel", "axis_distribution"}
    for axis_counts in summary["axis_distribution"].values():
        assert "mean" not in axis_counts
        assert set(axis_counts) == set(AGREEMENT_SCALE)
