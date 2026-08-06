"""Durable-path consumption of reviews: dispositions and criteria (E1/K4).

The durable fan-out is the only path production runs take, so the
aggregate commits must apply the same review effects as the in-process
nodes: a fatal full/simulation/recurrent finding changes the disposition
(E1), and the scientist's criteria select the scored axes the initial
gate consults (K4).
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from co_scientist.models import Hypothesis, HypothesisReview

from app import engine_tasks_fanout_aggregates as aggregates
from app import engine_tasks_fanout_reflection as reflection


def _make_item(result: dict[str, Any]) -> Any:
    """A stand-in item task carrying one completed per-item result."""

    class _Item:
        status = "completed"
        inputs: dict[str, Any] = {}
        result: dict[str, Any] = {}

    item = _Item()
    item.result = result
    return item


def _patch_items(
    monkeypatch: pytest.MonkeyPatch, results: dict[str, dict[str, Any]]
) -> None:
    """Serve canned item results from both aggregate modules."""

    def _require(item_id: Any, db_path: Any, kind: str = "") -> Any:
        return _make_item(results[str(item_id)])

    monkeypatch.setattr(reflection, "_require_item_task", _require)
    monkeypatch.setattr(aggregates, "_require_item_task", _require)


def test_mature_reflection_aggregate_applies_fatal_dispositions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected full review blocks the idea on the durable path too."""
    hypothesis = Hypothesis(text="idea")
    hypothesis.review_disposition = "viable"
    _patch_items(
        monkeypatch,
        {
            "item-full": {
                "hypothesis_id": hypothesis.id,
                "review_mode": "full",
                "review": {
                    "verdict": "rejected",
                    "justification": "circular mechanism",
                },
            },
            "item-simulation": {
                "hypothesis_id": hypothesis.id,
                "review_mode": "simulation",
                "review": {"verdict": "holds", "decisive_step": "step one"},
            },
        },
    )

    items = reflection._apply_mature_reflection_items(
        {hypothesis.id: hypothesis},
        ["item-full", "item-simulation"],
        current_iteration=1,
        db_path=None,
    )

    assert items.successful == 2
    assert hypothesis.enrichments["full"]["verdict"] == "rejected"
    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


def test_mature_reflection_aggregate_keeps_viable_for_sound_reviews(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-fatal canned verdicts leave the disposition where it was."""
    hypothesis = Hypothesis(text="idea")
    hypothesis.review_disposition = "viable"
    _patch_items(
        monkeypatch,
        {
            "item-full": {
                "hypothesis_id": hypothesis.id,
                "review_mode": "full",
                "review": {"verdict": "sound"},
            },
            "item-recurrent": {
                "hypothesis_id": hypothesis.id,
                "review_mode": "recurrent",
                "review": {"verdict": "sound"},
            },
        },
    )

    items = reflection._apply_mature_reflection_items(
        {hypothesis.id: hypothesis},
        ["item-full", "item-recurrent"],
        current_iteration=2,
        db_path=None,
    )

    assert items.successful == 2
    assert hypothesis.review_disposition == "viable"
    assert hypothesis.enrichments["recurrent_review_iteration"] == 2


def test_review_aggregate_gates_on_the_run_criteria(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The durable initial-review gate weighs the scientist's criteria."""
    hypothesis = Hypothesis(text="idea")
    review = HypothesisReview(
        review_summary="summary",
        scores={"scientific_soundness": 9, "novelty": 9, "testability": 1},
        safety_ethical_concerns="none",
        detailed_feedback={},
        constructive_feedback="feedback",
        overall_score=6.0,
    )
    _patch_items(
        monkeypatch,
        {
            "item-review": {
                "hypothesis_id": hypothesis.id,
                "review": dataclasses.asdict(review),
            }
        },
    )

    gated, failed = aggregates._apply_review_items(
        {hypothesis.id: hypothesis},
        ["item-review"],
        db_path=None,
        criteria=["Discriminating experimental design"],
    )

    assert (gated, failed) == (1, 0)
    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


def test_review_aggregate_without_criteria_keeps_the_default_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same scores pass when no criteria select the testability axis."""
    hypothesis = Hypothesis(text="idea")
    review = HypothesisReview(
        review_summary="summary",
        scores={"scientific_soundness": 9, "novelty": 9, "testability": 1},
        safety_ethical_concerns="none",
        detailed_feedback={},
        constructive_feedback="feedback",
        overall_score=6.0,
    )
    _patch_items(
        monkeypatch,
        {
            "item-review": {
                "hypothesis_id": hypothesis.id,
                "review": dataclasses.asdict(review),
            }
        },
    )

    gated, failed = aggregates._apply_review_items(
        {hypothesis.id: hypothesis}, ["item-review"], db_path=None
    )

    assert (gated, failed) == (1, 0)
    assert hypothesis.review_disposition == "viable"
    assert hypothesis.is_rankable()
