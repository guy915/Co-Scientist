"""Tests for the research-overview node's ``unexpected_research_directions``.

Task B: MASH's own published exemplar carries a fourth block,
``Unexpected Research Directions``, directly beneath its expanded
restatement of the five main directions -- genuinely new strategic
directions, not the same thing as ``unexpected_patterns`` (R12-10,
patterns observed across the ideas, not directions worth pursuing).
Split from ``test_research_overview`` on size; that module keeps the
node's other behavior (publication gates, top-k ranking, the evidence
corpus), the same split ``test_research_overview_directions.py`` (MO-1)
already made for the sibling per-direction sub-topic layer.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.meta_review import research_overview as ro
from tests._state import make_hypothesis, make_state


async def _run_overview_node(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]
) -> dict[str, Any]:
    """Runs the node against a canned LLM response; returns its state delta."""
    fake = AsyncMock(return_value=response)
    monkeypatch.setattr(ro, "call_llm_json", fake)
    h = make_hypothesis(
        text="HDAC inhibition reverses fibrosis", elo_rating=1700
    )
    state = make_state(
        hypotheses=[h],
        research_goal="g",
        supervisor_model_name="test/model",
        meta_review={},
    )
    return await ro.research_overview_node(state)


async def test_unexpected_research_directions_pass_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A well-formed unexpected direction survives into the state delta."""
    response = {
        "overview": {"summary": "S", "research_directions": []},
        "unexpected_research_directions": [
            {
                "title": "Nuclear LOXL2 as a Histone Modifier",
                "description": (
                    "Beyond crosslinking collagen, nuclear-translocated"
                    " LOXL2 may act as a histone aminooxidase."
                ),
            }
        ],
    }
    out = await _run_overview_node(monkeypatch, response)

    directions = out["research_overview"]["unexpected_research_directions"]
    assert directions == [
        {
            "title": "Nuclear LOXL2 as a Histone Modifier",
            "description": (
                "Beyond crosslinking collagen, nuclear-translocated"
                " LOXL2 may act as a histone aminooxidase."
            ),
        }
    ]


async def test_absent_unexpected_research_directions_defaults_to_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A response that omits the field degrades to an empty list, not KeyError.

    The schema declares it required, but nothing enforces that server-side
    under production's json_object downgrade, so a live response may still
    omit it.
    """
    response = {"overview": {"summary": "S", "research_directions": []}}
    out = await _run_overview_node(monkeypatch, response)

    assert out["research_overview"]["unexpected_research_directions"] == []
