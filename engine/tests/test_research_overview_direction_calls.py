"""Six research directions, developed one call each.

Google's published cf-PICI overview enumerates six main research
directions and develops five of them to 807-1,015 words apiece (the
sixth is its "Unexpected Areas of Research" block, which we mirror as
``unexpected_research_directions``). Ours asked for four, because the
draft call had to write every body itself: six at that density is ~13.9k
tokens on top of the ~9.9k the rest of the overview costs, which is the
whole 24000-token ceiling with nothing left for the chain of thought
sharing it, and 643-881s of generation at this deployment's measured
27-37 tokens per second against a 600s per-call bound.

So the draft names the six and argues each, and these pin what develops
them: one call per direction, concurrent, each bounded well inside the
clock; a direction that does not answer keeping its drafted title and
argument rather than taking its siblings down with it; a title the
writing call can never rename, since the overview's contacts
cross-reference it; and a direction the draft already developed never
bought a second time.

The offline deterministic backend cannot stand in for any of this: it
fills every array with exactly one item, so it can neither produce nor
disprove a six-direction answer.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.meta_review import (
    research_overview_direction_calls as calls,
)
from co_scientist.constants import RESEARCH_OVERVIEW_DIRECTION_MAX_TOKENS
from co_scientist.llm import ModelCallStats, record_call, scoped_telemetry
from co_scientist.schemas.synthesis import (
    RESEARCH_OVERVIEW_MAX_DIRECTIONS,
    RESEARCH_OVERVIEW_TARGET_DIRECTIONS,
)
from tests._state import make_state


def _context() -> calls.DirectionWaveContext:
    """The run material every writing call in these tests shares."""
    return calls.DirectionWaveContext(
        state=make_state(
            research_goal="Reverse liver fibrosis",
            supervisor_model_name="test/model",
        ),
        hypotheses_summary="1. an idea",
        evidence_corpus_text="evidence-1: a paper",
    )


def _drafted(count: int) -> list[dict[str, Any]]:
    """A draft's directions: named and argued, bodies left unwritten."""
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
    """One writing call's answer."""
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


async def test_the_ask_is_the_published_exemplar_s_own_count() -> None:
    """The draft asks for six, which is also what it is allowed to keep."""
    assert RESEARCH_OVERVIEW_TARGET_DIRECTIONS == 6
    assert (
        RESEARCH_OVERVIEW_TARGET_DIRECTIONS == RESEARCH_OVERVIEW_MAX_DIRECTIONS
    )


async def test_every_drafted_direction_buys_its_own_call() -> None:
    """Six directions are six concurrent calls, not one long stream."""
    ask = AsyncMock(return_value=_body())

    developed, spent = await calls.develop_research_directions(
        _context(), _drafted(RESEARCH_OVERVIEW_TARGET_DIRECTIONS), ask
    )

    assert spent == RESEARCH_OVERVIEW_TARGET_DIRECTIONS
    assert ask.await_count == RESEARCH_OVERVIEW_TARGET_DIRECTIONS
    assert len(developed) == RESEARCH_OVERVIEW_TARGET_DIRECTIONS
    assert all(direction["sub_topics"] for direction in developed)


async def test_each_call_is_bounded_well_inside_the_per_call_clock() -> None:
    """The budget is the split's whole point; a floor-sized one is not it."""
    ask = AsyncMock(return_value=_body())

    await calls.develop_research_directions(_context(), _drafted(1), ask)

    sent = ask.await_args_list[0].kwargs
    assert sent["spec"].max_tokens == RESEARCH_OVERVIEW_DIRECTION_MAX_TOKENS
    assert sent["options"].enable_thinking is False


async def test_a_writing_call_can_never_rename_its_direction() -> None:
    """The overview's contacts cross-reference a direction by its title."""
    ask = AsyncMock(return_value={**_body(), "title": "Renamed"})

    developed, _ = await calls.develop_research_directions(
        _context(), _drafted(1), ask
    )

    assert developed[0]["title"] == "Direction 0"


async def test_one_failing_call_costs_only_its_own_direction() -> None:
    """A raising sibling under one gather would cancel the rest of them."""
    ask = AsyncMock(side_effect=[RuntimeError("provider exploded"), _body()])

    developed, spent = await calls.develop_research_directions(
        _context(), _drafted(2), ask
    )

    assert spent == 2
    # The failed direction keeps what the draft gave it and publishes.
    assert developed[0]["title"] == "Direction 0"
    assert developed[0]["importance"] == "Why direction 0 matters."
    assert developed[0]["sub_topics"] == []
    assert developed[1]["sub_topics"]


async def test_a_field_the_writer_omitted_keeps_the_draft_s_own() -> None:
    """json_object mode enforces no required field, so a gap costs a field."""
    ask = AsyncMock(return_value={"sub_topics": _body()["sub_topics"]})

    developed, _ = await calls.develop_research_directions(
        _context(), _drafted(1), ask
    )

    assert developed[0]["importance"] == "Why direction 0 matters."
    assert developed[0]["sub_topics"]


async def test_a_direction_the_draft_developed_is_not_bought_twice() -> None:
    """A model that ignored the ask and wrote the body already did the work."""
    ask = AsyncMock(return_value=_body())
    drafted = _drafted(2)
    drafted[0] = {**drafted[0], **_body(), "title": "Direction 0"}

    developed, spent = await calls.develop_research_directions(
        _context(), drafted, ask
    )

    assert spent == 1
    assert ask.await_count == 1
    assert developed[0]["title"] == "Direction 0"


async def test_a_half_written_direction_is_still_bought_its_call() -> None:
    """One placeholder sub-topic is not a developed direction.

    A schema-enforcing provider requires every field whatever the prompt
    asks, so "the draft already wrote it" has to mean the whole body.
    """
    ask = AsyncMock(return_value=_body())
    drafted = _drafted(1)
    drafted[0]["sub_topics"] = [{"title": "Placeholder"}]

    _, spent = await calls.develop_research_directions(_context(), drafted, ask)

    assert spent == 1


async def test_every_call_is_told_the_whole_set_of_directions() -> None:
    """Six concurrent writers with no sight of each other repeat themselves."""
    ask = AsyncMock(return_value=_body())

    await calls.develop_research_directions(_context(), _drafted(3), ask)

    prompt = ask.await_args_list[0].kwargs["prompt"]
    assert "Direction 0" in prompt
    assert "Direction 1" in prompt
    assert "Direction 2" in prompt


async def test_the_wave_is_attributed_to_its_own_telemetry_sub_phase() -> None:
    """Folded into the node's bucket, the draft stops being measurable."""

    async def _record(**_: Any) -> dict[str, Any]:
        record_call("test/model", ModelCallStats(calls=1))
        return _body()

    with scoped_telemetry("research_overview") as accumulator:
        record_call("test/model", ModelCallStats(calls=1))
        await calls.develop_research_directions(
            _context(), _drafted(2), _record
        )

    snapshot = accumulator.snapshot()
    assert snapshot["research_overview::test/model"]["calls"] == 1
    assert snapshot["research_overview.directions::test/model"]["calls"] == 2


@pytest.mark.parametrize("directions", [None, "not a list", {}])
async def test_a_malformed_directions_value_buys_nothing(
    directions: Any,
) -> None:
    """The wave never turns a malformed draft into provider requests."""
    ask = AsyncMock(return_value=_body())

    developed, spent = await calls.develop_research_directions(
        _context(), directions, ask
    )

    assert developed == directions
    assert spent == 0
    ask.assert_not_awaited()
