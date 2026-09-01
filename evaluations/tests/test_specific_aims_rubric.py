"""Tests for the Specific Aims pilot-rubric export/import (Milestone 8).

Proves the rubric artifact (``evaluations/datasets/specific_aims_rubric_v1.
json``) is consumable, not inert: its 15 axes and 5-level scale match the
code exactly, and its two rated exemplars round-trip through the blinded
export/import to reproduce the published agreement counts. Also guards the
three caveats the corpus rows (R10-1/R10-10/R10-12) require to survive: the
instrument never overlaps ``expert_review.RATING_AXES``, the scale is never
averaged into a number, and nothing here compares a panel against the two
exemplars as a threshold.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from evaluations.expert_review import RATING_AXES, ExpertReviewValidationError
from evaluations.specific_aims_review import (
    AGREEMENT_SCALE,
    SPECIFIC_AIMS_AXES,
    SPECIFIC_AIMS_DOMAINS,
    SPECIFIC_AIMS_SCHEMA_VERSION,
    build_specific_aims_export,
    parse_specific_aims_ratings,
    summarize_specific_aims_ratings,
)

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
