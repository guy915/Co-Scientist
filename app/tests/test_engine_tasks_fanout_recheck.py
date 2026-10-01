"""The durable path gives a blocked idea one recheck, and only one.

The durable task path is the one production runs, so the bounded closure
of FIX-4 has to hold here: the reflection fan-out materializes one
recurrent review per blocked idea, the aggregate records the attempt from
the item's own inputs -- completed or not -- and a later cycle, reading
the pool back from the checkpoint, schedules nothing further.
"""

from __future__ import annotations

from typing import Any

import pytest
from co_scientist.models import Hypothesis, HypothesisReview

from app.engine_tasks import fanout_reflection as reflection
from app.engine_tasks.fanout import _mature_reflection_specs


def _patch_item(
    monkeypatch: pytest.MonkeyPatch, inputs: dict[str, Any], status: str
) -> None:
    """Serve one canned item task, carrying inputs but never a result."""

    class _Item:
        def __init__(self) -> None:
            self.inputs = inputs
            self.status = status
            self.result: dict[str, Any] | None = None

    monkeypatch.setattr(
        reflection,
        "_require_item_task",
        lambda item_id, db_path, kind="": _Item(),
    )


def _blocking_review() -> HypothesisReview:
    """An initial screen that lands in the not-viable band."""
    return HypothesisReview(
        review_summary="unsound",
        scores={"scientific_soundness": 2, "novelty": 8},
        safety_ethical_concerns="none",
        detailed_feedback={},
        constructive_feedback="rework",
        overall_score=3.0,
    )


def _blocked_hypothesis(text: str = "alpha") -> Hypothesis:
    """A hypothesis the initial review gate barred from the tournament."""
    hypothesis = Hypothesis(text=text, reviews=[_blocking_review()])
    hypothesis.review_disposition = "inaccurate"
    return hypothesis


def _state(hypotheses: list[Hypothesis]) -> dict[str, Any]:
    """A restored-state shape carrying only what the fan-out reads."""
    return {"hypotheses": hypotheses, "current_iteration": 0}


def test_the_fanout_schedules_one_recheck_per_blocked_idea() -> None:
    """Blocked ideas are unreachable from the cascade's viable filter."""
    pool = [_blocked_hypothesis(f"idea {index}") for index in range(20)]

    specs = _mature_reflection_specs(_state(pool))

    assert [spec.hypothesis_id for spec in specs] == [h.id for h in pool]
    assert all(spec.recheck for spec in specs)
    assert {spec.review_mode for spec in specs} == {"recurrent"}


def test_a_failed_recheck_item_still_records_its_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Marking only on success would re-fire the wave on every cycle."""
    hypothesis = _blocked_hypothesis()
    _patch_item(
        monkeypatch,
        {"hypothesis_id": hypothesis.id, "recheck": True},
        status="failed",
    )

    applied = reflection._apply_mature_reflection_items(
        {hypothesis.id: hypothesis}, ["item-1"], 0, None
    )

    assert applied.failed == 1
    assert _mature_reflection_specs(_state([hypothesis])) == []


def test_a_cascade_item_records_no_recheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The marker belongs to the recheck, not to every reflection item."""
    hypothesis = _blocked_hypothesis()
    _patch_item(
        monkeypatch,
        {"hypothesis_id": hypothesis.id, "review_mode": "full"},
        status="failed",
    )

    reflection._apply_mature_reflection_items(
        {hypothesis.id: hypothesis}, ["item-1"], 0, None
    )

    assert len(_mature_reflection_specs(_state([hypothesis]))) == 1


def test_the_cascade_still_owns_the_viable_ideas() -> None:
    """The recheck arm is additive: it changes no cascade scheduling."""
    viable = Hypothesis(text="cleared")
    viable.review_disposition = "viable"

    specs = _mature_reflection_specs(_state([viable, _blocked_hypothesis()]))

    assert [(spec.review_mode, spec.recheck) for spec in specs] == [
        ("full", False),
        ("simulation", False),
        ("recurrent", True),
    ]
