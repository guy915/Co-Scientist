"""Tests for the research-overview node's per-direction sub-topic layer.

MO-1 restores a nested sub-topic level beneath each research direction --
both published exemplars develop "what to research" as a list of named
sub-topics, not a flat experiment list. Split from ``test_research_overview``
on size; that module keeps the node's other behavior (publication gates,
top-k ranking, the evidence corpus).
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


def _direction_response(direction: dict[str, Any]) -> dict[str, Any]:
    """A minimal overview response carrying exactly one research direction."""
    return {"overview": {"summary": "S", "research_directions": [direction]}}


async def test_sub_topics_pass_through_when_well_formed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MO-1: a well-formed direction's sub-topic survives intact."""
    response = _direction_response(
        {
            "title": "T",
            "importance": "I",
            "suggested_experiments": ["E"],
            "sub_topics": [
                {
                    "title": "Sub-topic A",
                    "why": "Because Y.",
                    "what": "Investigate Z.",
                    "specific_questions": ["Does Z cause Y?"],
                }
            ],
        }
    )

    out = await _run_overview_node(monkeypatch, response)

    direction = out["research_overview"]["overview"]["research_directions"][0]
    assert direction["sub_topics"] == [
        {
            "title": "Sub-topic A",
            "why": "Because Y.",
            "what": "Investigate Z.",
            "specific_questions": ["Does Z cause Y?"],
        }
    ]


async def test_sub_topics_degrade_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A json_object-mode response omitting sub_topics never raises.

    The schema declares it required, but nothing enforces that
    server-side under the downgrade, so the model may still omit it --
    this must degrade to [], the same pattern
    ``_validate_research_contacts`` already follows for a missing field.
    """
    response = _direction_response(
        {"title": "T", "importance": "I", "suggested_experiments": ["E"]}
    )

    out = await _run_overview_node(monkeypatch, response)

    direction = out["research_overview"]["overview"]["research_directions"][0]
    assert direction["sub_topics"] == []


async def test_sub_topics_are_capped_at_the_schema_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """More sub-topics than the schema allows are capped, not trusted.

    json_object mode does not enforce ``maxItems`` server-side, so a
    non-conforming response is capped here defensively -- the same
    reason ``_validate_knowledge_base`` slices to its own max rather
    than accepting whatever the model returns.
    """
    response = _direction_response(
        {
            "title": "T",
            "importance": "I",
            "suggested_experiments": ["E"],
            "sub_topics": [
                {
                    "title": f"Topic {i}",
                    "why": "w",
                    "what": "w",
                    "specific_questions": [f"q{n}" for n in range(6)],
                }
                for i in range(6)
            ],
        }
    )

    out = await _run_overview_node(monkeypatch, response)

    sub_topics = out["research_overview"]["overview"]["research_directions"][0][
        "sub_topics"
    ]
    assert len(sub_topics) == 4
    assert [t["title"] for t in sub_topics] == [
        "Topic 0",
        "Topic 1",
        "Topic 2",
        "Topic 3",
    ]
    assert len(sub_topics[0]["specific_questions"]) == 4


async def test_malformed_sub_topics_are_dropped_not_crashed_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-dict sub-topic, or non-list questions, degrade, not raise."""
    response = _direction_response(
        {
            "title": "T",
            "importance": "I",
            "suggested_experiments": ["E"],
            "sub_topics": [
                {"title": "ok", "why": "w", "what": "w"},
                "not a dict",
                {
                    "title": "ok2",
                    "why": "w",
                    "what": "w",
                    "specific_questions": "not a list",
                },
            ],
        }
    )

    out = await _run_overview_node(monkeypatch, response)

    sub_topics = out["research_overview"]["overview"]["research_directions"][0][
        "sub_topics"
    ]
    assert [t["title"] for t in sub_topics] == ["ok", "ok2"]
    assert sub_topics[0]["specific_questions"] == []
    assert sub_topics[1]["specific_questions"] == []
