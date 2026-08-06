"""Debate prompt-content tests: scientist criteria and the turn envelope.

Split out of ``test_generation.py`` to keep that module within the size
cap.
"""

from typing import Any

import pytest

from co_scientist.agents.generation import debate
from co_scientist.agents.generation.debate import generate_with_debate
from co_scientist.prompts.generation_debate import (
    _DEBATE_MAX_DISCUSSION_TURNS,
)
from tests._state import make_state


async def test_debate_prompts_carry_scientist_criteria(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """State criteria steer the panel; absent criteria change nothing (A2)."""
    prompts: list[str] = []

    async def fake_call_llm(**kwargs: Any) -> str:
        prompts.append(str(kwargs["prompt"]))
        return "HYPOTHESIS: agreed"

    async def fake_call_llm_json(**kwargs: Any) -> dict[str, Any]:
        prompts.append(str(kwargs["prompt"]))
        return {
            "hypotheses": [
                {
                    "hypothesis": "the criteria-guided hypothesis",
                    "explanation": "because",
                    "literature_grounding": None,
                    "experiment": "run the assay",
                }
            ]
        }

    monkeypatch.setattr(debate, "call_llm", fake_call_llm)
    monkeypatch.setattr(debate, "call_llm_json", fake_call_llm_json)

    state = make_state(
        criteria=["Translational feasibility within five years"],
    )
    await generate_with_debate(state, count=1)

    assert any(
        "Scientist Evaluation Criteria" in prompt
        and "Translational feasibility within five years" in prompt
        for prompt in prompts
    )

    prompts.clear()
    await generate_with_debate(make_state(), count=1)
    assert all(
        "Scientist Evaluation Criteria" not in prompt for prompt in prompts
    )
    assert all("{{MISSING" not in prompt for prompt in prompts)


async def test_debate_prompt_states_the_envelope_from_the_loop_constants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The template's turn figures are the loop's constants (E13).

    A stale figure reads as a real instruction to the panel, so the prose
    and the enforced envelope are asserted against the same source.
    """
    from co_scientist.prompts.generation_debate import (
        _DEBATE_TYPICAL_MAX_TURNS,
        _DEBATE_TYPICAL_MIN_TURNS,
    )

    prompts: list[str] = []

    async def fake_call_llm(**kwargs: Any) -> str:
        prompts.append(str(kwargs["prompt"]))
        return "HYPOTHESIS: agreed"

    async def fake_call_llm_json(**kwargs: Any) -> dict[str, Any]:
        return {
            "hypotheses": [
                {
                    "hypothesis": "h",
                    "explanation": "because",
                    "literature_grounding": None,
                    "experiment": "run the assay",
                }
            ]
        }

    monkeypatch.setattr(debate, "call_llm", fake_call_llm)
    monkeypatch.setattr(debate, "call_llm_json", fake_call_llm_json)

    await generate_with_debate(make_state(), count=1)

    envelope = (
        f"typically {_DEBATE_TYPICAL_MIN_TURNS}-{_DEBATE_TYPICAL_MAX_TURNS}"
        f" conversational turns, with a maximum of "
        f"{_DEBATE_MAX_DISCUSSION_TURNS}"
    )
    assert all(envelope in prompt for prompt in prompts)
