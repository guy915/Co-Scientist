from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.meta_review import research_overview as ro
from co_scientist.agents.meta_review import (
    research_overview_direction_calls as calls,
)
from co_scientist.constants import RESEARCH_OVERVIEW_DIRECTION_MAX_TOKENS
from co_scientist.schemas.synthesis import (
    RESEARCH_OVERVIEW_MAX_DIRECTIONS,
    RESEARCH_OVERVIEW_TARGET_DIRECTIONS,
)
from tests._state import make_hypothesis, make_state


def _context() -> calls.DirectionWaveContext:
    return calls.DirectionWaveContext(
        state=make_state(
            research_goal="Reverse liver fibrosis",
            supervisor_model_name="test/model",
        ),
        hypotheses_summary="1. an idea",
        evidence_corpus_text="evidence-1: a paper",
    )


def _drafted(count: int) -> list[dict[str, Any]]:
    return [
        {
            "title": f"Direction {index}",
            "importance": f"Why direction {index} matters.",
            "recent_findings": "",
            "suggested_experiments": [],
            "sub_topics": [],
        }
        for index in range(count)
    ]


def _body() -> dict[str, Any]:
    return {
        "importance": "The developed argument.",
        "recent_findings": "What is already established.",
        "suggested_experiments": ["Knock it down and read out the marker."],
        "sub_topics": [
            {
                "title": "Sub-topic A",
                "why": "Because Y.",
                "what": "Investigate Z.",
                "example_idea": "Knock Z down and read out Y.",
                "specific_questions": ["Does Z cause Y?"],
            }
        ],
    }


async def test_every_drafted_direction_buys_its_own_bounded_call() -> None:
    ask = AsyncMock(return_value={**_body(), "title": "Renamed"})

    developed, spent = await calls.develop_research_directions(
        _context(), _drafted(RESEARCH_OVERVIEW_TARGET_DIRECTIONS), ask
    )

    assert spent == RESEARCH_OVERVIEW_TARGET_DIRECTIONS
    assert ask.await_count == RESEARCH_OVERVIEW_TARGET_DIRECTIONS
    assert all(direction["sub_topics"] for direction in developed)
    assert [d["title"] for d in developed] == [
        f"Direction {index}" for index in range(len(developed))
    ]
    sent = ask.await_args_list[0].kwargs
    assert sent["spec"].max_tokens == RESEARCH_OVERVIEW_DIRECTION_MAX_TOKENS
    assert sent["options"].enable_thinking is False
    assert all(
        f"Direction {index}" in sent["prompt"]
        for index in range(RESEARCH_OVERVIEW_TARGET_DIRECTIONS)
    )


async def test_one_failing_call_costs_only_its_own_direction() -> None:
    ask = AsyncMock(side_effect=[RuntimeError("provider exploded"), _body()])

    developed, spent = await calls.develop_research_directions(
        _context(), _drafted(2), ask
    )

    assert spent == 2
    assert developed[0]["title"] == "Direction 0"
    assert developed[0]["importance"] == "Why direction 0 matters."
    assert developed[0]["sub_topics"] == []
    assert developed[1]["sub_topics"]


async def _research_overview_directions_run_overview_node(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]
) -> dict[str, Any]:
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
    return {"overview": {"summary": "S", "research_directions": [direction]}}


async def test_missing_direction_detail_degrades_to_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _direction_response(
        {
            "title": "T",
            "importance": "I",
            "suggested_experiments": ["E"],
            "sub_topics": [{"title": "Sub-topic A", "why": "w", "what": "w"}],
        }
    )
    plain = _direction_response(
        {"title": "T", "importance": "I", "suggested_experiments": ["E"]}
    )

    out = await _research_overview_directions_run_overview_node(
        monkeypatch, response
    )
    plain_out = await _research_overview_directions_run_overview_node(
        monkeypatch, plain
    )

    direction = out["research_overview"]["overview"]["research_directions"][0]
    assert direction["sub_topics"][0]["example_idea"] == ""
    bare = plain_out["research_overview"]["overview"]["research_directions"][0]
    assert bare["sub_topics"] == []
    assert bare["recent_findings"] == ""
    assert (
        plain_out["research_overview"]["unexpected_research_directions"] == []
    )


async def test_sub_topics_are_capped_and_malformed_ones_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The json_object downgrade does not enforce maxItems server-side."""
    many = _direction_response(
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
    malformed = _direction_response(
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

    capped = await _research_overview_directions_run_overview_node(
        monkeypatch, many
    )
    kept = await _research_overview_directions_run_overview_node(
        monkeypatch, malformed
    )

    sub_topics = capped["research_overview"]["overview"]["research_directions"][
        0
    ]["sub_topics"]
    assert [t["title"] for t in sub_topics] == [f"Topic {i}" for i in range(4)]
    assert len(sub_topics[0]["specific_questions"]) == 4
    salvaged = kept["research_overview"]["overview"]["research_directions"][0][
        "sub_topics"
    ]
    assert [t["title"] for t in salvaged] == ["ok", "ok2"]
    assert [t["specific_questions"] for t in salvaged] == [[], []]


async def test_research_directions_are_capped_at_the_schema_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directions = [
        {
            "title": f"Direction {i}",
            "importance": "I",
            "suggested_experiments": ["E"],
            "sub_topics": [],
        }
        for i in range(9)
    ]
    response = {"overview": {"summary": "S", "research_directions": directions}}

    out = await _research_overview_directions_run_overview_node(
        monkeypatch, response
    )

    kept = out["research_overview"]["overview"]["research_directions"]
    assert len(kept) == RESEARCH_OVERVIEW_MAX_DIRECTIONS
    assert kept[0]["title"] == "Direction 0"
