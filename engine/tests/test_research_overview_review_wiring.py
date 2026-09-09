"""Tests for the research-overview node's accuracy-review wiring.

Split out of ``test_research_overview.py`` to stay under the file-length
cap. The review/revise cycle itself is pinned in
``test_research_overview_review.py`` against the LLM boundary. These pin
the node's wiring: the tier gate, the published-prose swap on a revision,
and the never-fail-the-run degradation on any loop failure.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.meta_review import research_overview as ro
from tests._state import make_hypothesis, make_state
from tests.test_research_overview import _OVERVIEW_RESPONSE, _grounded_articles

_DIRECTIONS = len(_OVERVIEW_RESPONSE["overview"]["research_directions"])
"""Directions the canned draft names, each bought its own writing call."""


def _base_state(**overrides: Any) -> Any:
    h = make_hypothesis(
        text="HDAC inhibition reverses fibrosis", elo_rating=1700
    )
    return make_state(
        hypotheses=[h],
        research_goal="g",
        supervisor_model_name="test/model",
        meta_review={},
        articles=_grounded_articles(),
        **overrides,
    )


async def test_review_disabled_by_default_skips_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``enable_overview_review`` flag means the loop never runs."""
    synth = AsyncMock(return_value=_OVERVIEW_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", synth)
    loop = AsyncMock(side_effect=AssertionError("loop must not run"))
    monkeypatch.setattr(ro, "review_research_overview", loop)

    out = await ro.research_overview_node(_base_state())

    loop.assert_not_awaited()
    assert out["research_overview"]["overview_review"] == {
        "reviewed": False,
        "rounds": 0,
    }
    # Two calls: the draft, plus the one call that develops its single
    # drafted direction (research_overview_direction_calls).
    assert out["metrics"].llm_calls == 2


async def test_a_review_round_changes_the_published_overview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A revision the loop returns is what actually publishes."""
    synth = AsyncMock(return_value=_OVERVIEW_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", synth)
    revised = {
        **_OVERVIEW_RESPONSE,
        "overview": {
            **_OVERVIEW_RESPONSE["overview"],
            "summary": "Corrected, hedged summary.",
        },
    }
    loop = AsyncMock(return_value=(revised, {"reviewed": True, "rounds": 1}, 3))
    monkeypatch.setattr(ro, "review_research_overview", loop)

    out = await ro.research_overview_node(
        _base_state(enable_overview_review=True)
    )

    loop.assert_awaited_once()
    assert (
        out["research_overview"]["overview"]["summary"]
        == "Corrected, hedged summary."
    )
    assert out["research_overview"]["overview_review"] == {
        "reviewed": True,
        "rounds": 1,
    }
    # One synthesis call, the three the loop reports spending, and one
    # per drafted direction developed afterwards.
    assert out["metrics"].llm_calls == 4 + _DIRECTIONS


async def test_an_exception_in_the_review_loop_publishes_the_original_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A report that fails to publish is worse than one that is unreviewed.

    Any exception in the review loop must degrade to the drafted overview
    exactly as synthesized -- never raise out of the node.
    """
    synth = AsyncMock(return_value=_OVERVIEW_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", synth)
    loop = AsyncMock(side_effect=RuntimeError("provider exploded"))
    monkeypatch.setattr(ro, "review_research_overview", loop)

    out = await ro.research_overview_node(
        _base_state(enable_overview_review=True)
    )

    loop.assert_awaited_once()
    assert out["research_overview"]["overview"]["summary"] == "S"
    assert out["research_overview"]["overview_review"] == {
        "reviewed": False,
        "rounds": 0,
    }
    # Two calls: the draft, plus the one call that develops its single
    # drafted direction (research_overview_direction_calls).
    assert out["metrics"].llm_calls == 2
