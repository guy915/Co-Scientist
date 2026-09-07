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

from co_scientist.agents.generation import coordinator
from co_scientist.agents.meta_review import research_overview as ro
from co_scientist.scheduling import TaskType
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
    augmented = coordinator._with_interim_overview(state, "Paper A says X.")

    assert augmented is not None
    assert "Direction 1: block the brake." in augmented
    assert "Paper A says X." in augmented


async def test_prepare_generation_splices_the_block_into_its_context() -> None:
    """The splice itself, at the seam every strategy is handed.

    ``_with_interim_overview`` being correct in isolation is not the fix:
    the call in ``_prepare_generation`` is what puts it in front of the
    generation prompts.
    """
    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=2,
        mcp_available=True,
        articles_with_reasoning="Paper A says X.",
        interim_overview="Direction 1: block the brake.",
    )

    _, _, context = await coordinator._prepare_generation(state)

    assert context is not None
    assert "Direction 1: block the brake." in context
    assert "Paper A says X." in context


def test_generation_context_is_untouched_before_the_first_firing() -> None:
    """No firing yet means byte-identical prompts to before this fix."""
    state = make_state()
    unchanged = coordinator._with_interim_overview(state, "Paper A says X.")
    assert unchanged == "Paper A says X."
    assert coordinator._with_interim_overview(state, None) is None
