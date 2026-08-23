"""Tests for the research-overview accuracy review/revise loop.

``review_research_overview`` is the sibling-module loop
``research_overview.py`` re-exports. These tests monkeypatch
``call_llm_json`` on the loop's own module -- the LLM boundary -- so no
provider or network call is made, and pin the loop's cycle shape: a cheap
accept, a revision that changes the published prose, and the hard cycle
cap.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.meta_review import research_overview_review as ror
from tests._state import make_state

_DRAFT: dict[str, Any] = {
    "overview": {"summary": "Original summary.", "research_directions": []},
    "nih_specific_aims": {"introduction": "i", "aims": [], "impact": "imp"},
    "research_contacts": [],
    "knowledge_base": [],
}


def _revised(summary: str) -> dict[str, Any]:
    """A reviser response identical to ``_DRAFT`` but for the summary."""
    return {
        "overview": {"summary": summary, "research_directions": []},
        "nih_specific_aims": {"introduction": "i", "aims": [], "impact": "imp"},
        "research_contacts": [],
        "knowledge_base": [],
    }


def _reject(location: str = "overview.summary") -> dict[str, Any]:
    return {
        "accept": False,
        "notes": [{"location": location, "issue": "Unsupported claim."}],
    }


async def _run_loop(
    state: Any, draft: dict[str, Any] = _DRAFT
) -> tuple[dict[str, Any], dict[str, Any], int]:
    context = ror.OverviewReviewContext(
        state=state,
        research_goal="g",
        hypotheses_summary="1. (Elo 1600) h",
        contact_candidates_text="No verified literature authors available.",
        evidence_corpus_text="No verified evidence corpus available.",
    )
    return await ror.review_research_overview(context, draft)


async def test_accept_first_time_runs_no_reviser_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A first-pass accept costs one call and leaves the draft untouched."""
    fake = AsyncMock(return_value={"accept": True})
    monkeypatch.setattr(ror, "call_llm_json", fake)

    state = make_state(supervisor_model_name="test/model")
    final, meta, calls = await _run_loop(state)

    assert fake.await_count == 1
    assert final is _DRAFT
    assert meta == {"reviewed": False, "rounds": 0}
    assert calls == 1


async def test_a_revision_round_changes_the_published_prose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejection followed by acceptance publishes the revised prose."""
    revised = _revised("Corrected, hedged summary.")
    fake = AsyncMock(side_effect=[_reject(), revised, {"accept": True}])
    monkeypatch.setattr(ror, "call_llm_json", fake)

    state = make_state(supervisor_model_name="test/model")
    final, meta, calls = await _run_loop(state)

    assert fake.await_count == 3
    assert final["overview"]["summary"] == "Corrected, hedged summary."
    assert final["overview"]["summary"] != _DRAFT["overview"]["summary"]
    assert meta == {"reviewed": True, "rounds": 1}
    assert calls == 3


async def test_the_cycle_cap_holds_when_the_reviewer_objects_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reviewer is asked at most twice; the last revision publishes."""
    second_revision = _revised("Second revision.")
    fake = AsyncMock(
        side_effect=[
            _reject("overview.summary"),
            _revised("First revision."),
            _reject("aims[0]"),
            second_revision,
        ]
    )
    monkeypatch.setattr(ror, "call_llm_json", fake)

    state = make_state(supervisor_model_name="test/model")
    final, meta, calls = await _run_loop(state)

    # Two review calls, two revise calls -- no third review call spent on
    # a verdict that could not change the outcome.
    assert fake.await_count == 4
    assert calls == 4
    assert final["overview"]["summary"] == "Second revision."
    assert meta == {"reviewed": True, "rounds": 2}
