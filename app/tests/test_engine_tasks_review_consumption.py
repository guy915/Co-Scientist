from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from co_scientist.models import Hypothesis, HypothesisReview

from app.engine_tasks import fanout_aggregates as aggregates
from app.engine_tasks import fanout_aggregates as reflection


def _make_item(result: dict[str, Any]) -> Any:

    class _Item:
        status = "completed"

        def __init__(self, payload: dict[str, Any]) -> None:
            self.inputs: dict[str, Any] = {}
            self.result: dict[str, Any] = payload

    return _Item(result)


def _patch_items(
    monkeypatch: pytest.MonkeyPatch, results: dict[str, dict[str, Any]]
) -> None:

    def _require(item_id: Any, db_path: Any, kind: str = "") -> Any:
        return _make_item(results[str(item_id)])

    monkeypatch.setattr(reflection, "_require_item_task", _require)
    monkeypatch.setattr(aggregates, "_require_item_task", _require)


def test_mature_reflection_aggregate_applies_fatal_dispositions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    gated, failed, _usage = aggregates._apply_review_items(
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

    gated, failed, _usage = aggregates._apply_review_items(
        {hypothesis.id: hypothesis}, ["item-review"], db_path=None
    )

    assert (gated, failed) == (1, 0)
    assert hypothesis.review_disposition == "viable"
    assert hypothesis.is_rankable()


def test_the_aggregate_carries_each_item_s_research_to_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Retrieval ledgers belong to the run and must survive discarded item
    # results without duplicate searches.
    hypothesis = Hypothesis(text="idea")
    hypothesis.review_disposition = "viable"
    ledger = {"goal": "reverse fibrosis", "calls": []}
    _patch_items(
        monkeypatch,
        {
            "item-full": {
                "hypothesis_id": hypothesis.id,
                "review_mode": "full",
                "review": {"verdict": "sound"},
                "research_ledger": ledger,
            },
            "item-simulation": {
                "hypothesis_id": hypothesis.id,
                "review_mode": "simulation",
                "review": {"verdict": "holds"},
                "research_ledger": dict(ledger),
            },
        },
    )

    items = reflection._apply_mature_reflection_items(
        {hypothesis.id: hypothesis},
        ["item-full", "item-simulation"],
        current_iteration=1,
        db_path=None,
    )
    update = reflection._mature_reflection_update(
        {"hypotheses": [hypothesis], "articles": []}, items
    )

    assert update["research_ledgers"] == [ledger]


def test_an_unresearched_review_adds_no_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hypothesis = Hypothesis(text="idea")
    hypothesis.review_disposition = "viable"
    _patch_items(
        monkeypatch,
        {
            "item-full": {
                "hypothesis_id": hypothesis.id,
                "review_mode": "full",
                "review": {"verdict": "sound"},
                "research_ledger": None,
            }
        },
    )

    items = reflection._apply_mature_reflection_items(
        {hypothesis.id: hypothesis},
        ["item-full"],
        current_iteration=1,
        db_path=None,
    )

    assert items.research_ledgers == []
