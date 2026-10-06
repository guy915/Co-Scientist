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
    SPECIFIC_AIMS_SCHEMA_VERSION,
    build_specific_aims_export,
    parse_specific_aims_ratings,
    summarize_specific_aims_ratings,
)


def _quality_rating(rater_id: str = "expert-1", **scores: int) -> dict[str, Any]:
    return {
        "rater_id": rater_id,
        "item_id": "item-a",
        **dict.fromkeys(RATING_AXES, 4),
        "preference_rank": 1,
        **scores,
    }


def _quality_payload(*rows: dict[str, Any], version: int = SCHEMA_VERSION) -> dict[str, Any]:
    return {"schema_version": version, "ratings": list(rows)}


@pytest.mark.parametrize("build", [build_blinded_export, build_specific_aims_export])
def test_exports_are_blinded_with_stable_item_ids(build: Any) -> None:
    pool = [{"id": "h1", "text": "idea", "elo_rating": 1400, "origin": "x"}]

    export = build("run-1", pool)

    assert [set(item) for item in export["items"]] == [{"item_id", "text"}]
    assert export["items"] == build("run-1", pool)["items"]
    assert export["items"][0]["item_id"].startswith("item-")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (_quality_payload(_quality_rating(novelty=9)), "novelty"),
        (
            _quality_payload({k: v for k, v in _quality_rating().items() if k != "alignment"}),
            "alignment",
        ),
        (_quality_payload(version=999), "schema"),
        (_quality_payload(_quality_rating(), _quality_rating()), "duplicate"),
    ],
)
def test_invalid_expert_ratings_fail_closed(payload: dict[str, Any], message: str) -> None:
    with pytest.raises(ExpertReviewValidationError, match=message):
        parse_ratings(payload)


def test_panel_summary_reports_confidence_and_agreement() -> None:
    ratings = parse_ratings(
        _quality_payload(
            _quality_rating(alignment=5, novelty=3),
            _quality_rating("expert-2", novelty=3, impact=3),
        )
    )

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


_DATASET = json.loads(
    (
        pathlib.Path(__file__).resolve().parent.parent / "datasets" / "specific_aims_rubric_v1.json"
    ).read_text(encoding="utf-8")
)


def _aims_payload(ratings: dict[str, str]) -> dict[str, Any]:
    return {
        "schema_version": SPECIFIC_AIMS_SCHEMA_VERSION,
        "ratings": [{"rater_id": "rater-1", "item_id": "item-x", "ratings": ratings}],
    }


def test_dataset_axes_match_the_code_exactly() -> None:
    domains = _DATASET["rubric"]["domains"]
    axes = tuple(entry["axis"] for domain in domains.values() for entry in domain)
    assert axes == SPECIFIC_AIMS_AXES
    assert tuple(_DATASET["rubric"]["scale"]["levels"]) == AGREEMENT_SCALE


@pytest.mark.parametrize("case", ["lapatinib_colon_cancer", "selinexor_colon_cancer"])
def test_published_exemplars_round_trip_to_their_own_counts(case: str) -> None:
    exemplar = next(e for e in _DATASET["exemplars"] if e["case"] == case)

    parsed = parse_specific_aims_ratings(_aims_payload(exemplar["ratings"]))
    summary = summarize_specific_aims_ratings(parsed)

    counts = dict.fromkeys(AGREEMENT_SCALE, 0)
    for axis_counts in summary["axis_distribution"].values():
        assert set(axis_counts) == set(AGREEMENT_SCALE)
        for level, n in axis_counts.items():
            counts[level] += n
    assert counts == exemplar["published_counts"]
    assert set(summary) == {"schema_version", "panel", "axis_distribution"}


@pytest.mark.parametrize("fault", ["malformed", "missing"])
def test_incomplete_aims_ratings_fail_closed(fault: str) -> None:
    ratings = dict.fromkeys(SPECIFIC_AIMS_AXES, "agree")
    if fault == "malformed":
        ratings["unmet_clinical_needs"] = "somewhat_agree"
    else:
        del ratings[SPECIFIC_AIMS_AXES[-1]]
    with pytest.raises(ExpertReviewValidationError):
        parse_specific_aims_ratings(_aims_payload(ratings))
