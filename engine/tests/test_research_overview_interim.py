"""FIX-6: what a non-terminal overview firing writes, and what reads it.

The scheduling and routing half of this fix is pinned by
``test_scheduling_policy_overview.py``. This is the node half: a periodic
firing must write an ``interim_overview`` for generation to read and must
*not* overwrite ``research_overview``, which the live UI and the finished
report both read; and it must not buy the terminal firing's extras (the
accuracy review loop, the deep knowledge-base synthesis), which exist to
make the published document, not to steer the next generate cycle.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.generation import operations
from co_scientist.agents.meta_review import research_overview as ro
from co_scientist.constants import (
    RESEARCH_OVERVIEW_INTERIM_MAX_TOKENS,
    RESEARCH_OVERVIEW_MAX_TOKENS,
)
from co_scientist.scheduling import TaskType
from co_scientist.schemas.synthesis import RESEARCH_OVERVIEW_SCHEMA
from tests._state import make_article, make_hypothesis, make_state

_RESPONSE: dict[str, Any] = {
    "overview": {
        "summary": "Where the evidence points.",
        "research_directions": [
            {
                "title": "Releasing the myeloid brake",
                "importance": "It unlocks fibrolysis.",
                "suggested_experiments": ["Block LILRB4."],
            }
        ],
    },
    "nih_specific_aims": {},
    "open_questions": ["What sets the reversal threshold?"],
    "knowledge_base": [],
}


def _state(**overrides: Any) -> Any:
    return make_state(
        hypotheses=[make_hypothesis(text="an idea", elo_rating=1700)],
        research_goal="g",
        supervisor_model_name="test/model",
        meta_review={},
        articles=[make_article(used_in_analysis=True)],
        enable_overview_review=True,
        budget={"max_iterations": 3, "max_llm_calls": 7000},
        **overrides,
    )


async def test_a_periodic_firing_writes_only_the_interim_overview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``research_overview`` stays the published document's own key."""
    monkeypatch.setattr(ro, "call_llm_json", AsyncMock(return_value=_RESPONSE))

    out = await ro.research_overview_node(
        _state(next_task=TaskType.SYNTHESIZE.value)
    )

    assert "research_overview" not in out
    assert "Releasing the myeloid brake" in out["interim_overview"]
    assert "What sets the reversal threshold?" in out["interim_overview"]


async def test_a_periodic_firing_buys_neither_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One call: no accuracy-review loop, no deep knowledge-base call."""
    fake = AsyncMock(return_value=_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", fake)
    review = AsyncMock()
    monkeypatch.setattr(ro, "review_research_overview", review)
    deep = AsyncMock()
    monkeypatch.setattr(ro, "synthesize_knowledge_base", deep)

    await ro.research_overview_node(_state(next_task=TaskType.SYNTHESIZE.value))

    assert fake.await_count == 1
    assert review.await_count == 0
    assert deep.await_count == 0


async def test_a_periodic_firing_asks_only_for_directions_and_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The interim call's own schema, not the terminal document's ten.

    Before this schema existed every periodic firing still paid for the
    NIH Specific Aims page, the contacts and the knowledge base at the
    terminal call's own generation cost, and discarded all of it --
    ``build_interim_overview`` only ever reads direction titles and open
    questions back out.
    """
    fake = AsyncMock(return_value=_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", fake)

    await ro.research_overview_node(_state(next_task=TaskType.SYNTHESIZE.value))

    assert fake.await_args is not None
    schema = fake.await_args.kwargs["spec"].json_schema
    assert schema is not None
    properties = schema["schema"]["properties"]
    assert set(properties) == {"overview", "open_questions"}
    assert set(properties["overview"]["properties"]) == {"research_directions"}
    direction_item = properties["overview"]["properties"][
        "research_directions"
    ]["items"]
    assert set(direction_item["properties"]) == {"title"}
    assert "nih_specific_aims" not in properties
    assert "research_contacts" not in properties
    assert "knowledge_base" not in properties


def test_the_interim_schema_is_a_strict_subset_of_the_terminal_one() -> None:
    """Direction titles and open questions only -- named once, reused.

    ``RESEARCH_OVERVIEW_INTERIM_MAX_DIRECTIONS``/``_MAX_QUESTIONS`` are the
    same constants ``interim_overview.build_interim_overview`` renders
    from, so this call is never asked to write a title or question the
    next generate cycle will not see.
    """
    from co_scientist.schemas.synthesis import RESEARCH_OVERVIEW_INTERIM_SCHEMA

    terminal_top = set(RESEARCH_OVERVIEW_SCHEMA["schema"]["properties"])
    interim_top = set(RESEARCH_OVERVIEW_INTERIM_SCHEMA["schema"]["properties"])
    assert interim_top < terminal_top

    terminal_overview = set(
        RESEARCH_OVERVIEW_SCHEMA["schema"]["properties"]["overview"][
            "properties"
        ]
    )
    interim_overview_props = set(
        RESEARCH_OVERVIEW_INTERIM_SCHEMA["schema"]["properties"]["overview"][
            "properties"
        ]
    )
    assert interim_overview_props < terminal_overview


async def test_a_periodic_firing_is_budgeted_below_the_terminal_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tiny ask does not need the terminal document's base budget.

    Whether this actually lowers the deployed chain's *effective*
    ceiling depends on whether the model thinks -- see
    ``RESEARCH_OVERVIEW_INTERIM_MAX_TOKENS``'s own docstring -- but the
    base budget passed to the call is smaller either way.
    """
    fake = AsyncMock(return_value=_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", fake)

    await ro.research_overview_node(_state(next_task=TaskType.SYNTHESIZE.value))

    assert fake.await_args is not None
    spec = fake.await_args.kwargs["spec"]
    assert spec.max_tokens == RESEARCH_OVERVIEW_INTERIM_MAX_TOKENS
    assert spec.max_tokens < RESEARCH_OVERVIEW_MAX_TOKENS


async def test_the_terminal_firing_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TERMINATE still publishes the overview and writes no interim."""
    monkeypatch.setattr(ro, "call_llm_json", AsyncMock(return_value=_RESPONSE))
    monkeypatch.setattr(
        ro, "synthesize_knowledge_base", AsyncMock(return_value=([], 0))
    )
    monkeypatch.setattr(
        ro,
        "review_research_overview",
        AsyncMock(return_value=(_RESPONSE, {"reviewed": True, "rounds": 1}, 1)),
    )

    out = await ro.research_overview_node(
        _state(next_task=TaskType.TERMINATE.value)
    )

    assert "interim_overview" not in out
    assert out["research_overview"]["overview"]["summary"]


def test_generation_reads_the_interim_overview_as_context() -> None:
    """The feedback edge lands where the generation prompts already read.

    Spliced onto the literature context the strategies are handed rather
    than into a new prompt slot: the block describes this run's own
    findings so far, which is what that context is.
    """
    state = make_state(interim_overview="Direction 1: block the brake.")
    augmented = operations._with_interim_overview(state, "Paper A says X.")

    assert augmented is not None
    assert "Direction 1: block the brake." in augmented
    assert "Paper A says X." in augmented


async def test_prepare_generation_splices_the_block_into_its_context() -> None:
    """The splice itself, at the seam every strategy is handed.

    ``_with_interim_overview`` being correct in isolation is not the fix:
    the call in ``prepare_generation`` is what puts it in front of the
    generation prompts.
    """
    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=2,
        mcp_available=True,
        articles_with_reasoning="Paper A says X.",
        interim_overview="Direction 1: block the brake.",
    )

    context = (await operations.prepare_generation(state)).literature

    assert context is not None
    assert "Direction 1: block the brake." in context
    assert "Paper A says X." in context


def test_generation_context_is_untouched_before_the_first_firing() -> None:
    """No firing yet means byte-identical prompts to before this fix."""
    state = make_state()
    unchanged = operations._with_interim_overview(state, "Paper A says X.")
    assert unchanged == "Paper A says X."
    assert operations._with_interim_overview(state, None) is None
