from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from co_scientist.models import Hypothesis, HypothesisReview

from app.engine_tasks import fanout_aggregates as aggregates


def _patch_items(
    monkeypatch: pytest.MonkeyPatch, results: dict[str, dict[str, Any]]
) -> None:

    class _Item:
        status = "completed"

        def __init__(self, payload: dict[str, Any]) -> None:
            self.inputs: dict[str, Any] = {}
            self.result: dict[str, Any] = payload

    monkeypatch.setattr(
        aggregates,
        "_require_item_task",
        lambda item_id, db_path, kind="": _Item(results[str(item_id)]),
    )


def _mature_item(
    hypothesis: Hypothesis, mode: str, review: dict[str, Any], **extra: Any
) -> dict[str, Any]:
    return {
        "hypothesis_id": hypothesis.id,
        "review_mode": mode,
        "review": review,
        **extra,
    }


def test_mature_reflection_aggregate_applies_fatal_dispositions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hypothesis = Hypothesis(text="idea")
    hypothesis.review_disposition = "viable"
    _patch_items(
        monkeypatch,
        {
            "item-full": _mature_item(
                hypothesis,
                "full",
                {"verdict": "rejected", "justification": "circular"},
            ),
            "item-simulation": _mature_item(
                hypothesis, "simulation", {"verdict": "holds"}
            ),
        },
    )

    items = aggregates._apply_mature_reflection_items(
        {hypothesis.id: hypothesis},
        ["item-full", "item-simulation"],
        current_iteration=1,
        db_path=None,
    )

    assert items.successful == 2
    assert hypothesis.enrichments["full"]["verdict"] == "rejected"
    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


@pytest.mark.parametrize(
    ("criteria", "disposition"),
    [(["Discriminating experimental design"], "inaccurate"), (None, "viable")],
)
def test_review_aggregate_gates_on_the_run_criteria_when_it_has_any(
    monkeypatch: pytest.MonkeyPatch,
    criteria: list[str] | None,
    disposition: str,
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
        criteria=criteria,
    )

    assert (gated, failed) == (1, 0)
    assert hypothesis.review_disposition == disposition
    assert hypothesis.is_rankable() is (disposition == "viable")


@pytest.mark.parametrize(
    "ledger", [{"goal": "reverse fibrosis", "calls": []}, None]
)
def test_the_aggregate_carries_each_items_research_to_the_run_once(
    monkeypatch: pytest.MonkeyPatch, ledger: dict[str, Any] | None
) -> None:
    # Retrieval ledgers belong to the run and must survive discarded item
    # results without duplicate searches.
    hypothesis = Hypothesis(text="idea")
    hypothesis.review_disposition = "viable"
    _patch_items(
        monkeypatch,
        {
            "item-full": _mature_item(
                hypothesis, "full", {"verdict": "sound"}, research_ledger=ledger
            ),
            "item-simulation": _mature_item(
                hypothesis,
                "simulation",
                {"verdict": "holds"},
                research_ledger=dict(ledger) if ledger else None,
            ),
        },
    )

    items = aggregates._apply_mature_reflection_items(
        {hypothesis.id: hypothesis},
        ["item-full", "item-simulation"],
        current_iteration=1,
        db_path=None,
    )
    update = aggregates._mature_reflection_update(
        {"hypotheses": [hypothesis], "articles": []}, items
    )

    assert update["research_ledgers"] == ([ledger] if ledger else [])
