"""Tests for debate-based generation and the generate_node wrapper.

``generate_with_debate`` runs multi-turn debates (each non-final turn calls
``call_llm`` and the final turn calls ``call_llm_json``) to produce one
Hypothesis per debate; these tests stub both LLM calls. ``generate_node`` is a
thin wrapper that delegates to the generation coordinator and attaches metrics.
"""

from typing import Any

import pytest

from co_scientist.agents.generation import debate
from co_scientist.agents.generation import generate as generate_mod
from co_scientist.agents.generation.debate import (
    generate_with_debate,
)
from co_scientist.agents.generation.generate import generate_node
from co_scientist.constants import DEBATE_MAX_TURNS
from co_scientist.exceptions import GenerationError
from co_scientist.models import GenerationMethod
from tests._state import make_hypothesis, make_state


def _stub_debate_llm(monkeypatch: pytest.MonkeyPatch, final_text: str) -> None:
    """Stub debate turns (call_llm) and the final hypothesis (call_llm_json)."""

    async def fake_call_llm(**_: Any) -> str:
        return "a debate turn argument"

    async def fake_call_llm_json(**_: Any) -> dict[str, Any]:
        return {
            "hypotheses": [
                {
                    "hypothesis": final_text,
                    "explanation": "because the mechanism fits",
                    "literature_grounding": None,
                    "experiment": "run the assay",
                }
            ]
        }

    monkeypatch.setattr(debate, "call_llm", fake_call_llm)
    monkeypatch.setattr(debate, "call_llm_json", fake_call_llm_json)


async def test_count_zero_returns_empty() -> None:
    """Requesting zero debates short-circuits without any LLM call."""
    hyps, transcripts = await generate_with_debate(make_state(), count=0)
    assert hyps == []
    assert transcripts == []


def _stub_debate_llm_counting(
    monkeypatch: pytest.MonkeyPatch, turn_texts: list[str]
) -> tuple[list[str], list[int]]:
    """Stub debate turns with scripted text, counting calls of each kind."""
    free_form: list[str] = []
    finals: list[int] = []

    async def fake_call_llm(**_: Any) -> str:
        text = turn_texts[len(free_form)]
        free_form.append(text)
        return text

    async def fake_call_llm_json(**_: Any) -> dict[str, Any]:
        finals.append(1)
        return {
            "hypotheses": [
                {
                    "hypothesis": "converged idea",
                    "explanation": "because the mechanism fits",
                    "literature_grounding": None,
                    "experiment": "run the assay",
                }
            ]
        }

    monkeypatch.setattr(debate, "call_llm", fake_call_llm)
    monkeypatch.setattr(debate, "call_llm_json", fake_call_llm_json)
    return free_form, finals


async def test_declared_convergence_ends_the_debate_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn writing the HYPOTHESIS sentinel skips to the final turn.

    The prompt's termination condition asks the panel to conclude with
    "HYPOTHESIS" in capitals; honouring it retires the remaining free-form
    turns of the budget, which are serial LLM calls.
    """
    free_form, finals = _stub_debate_llm_counting(
        monkeypatch,
        ["still arguing", "HYPOTHESIS: the panel agrees", "unreached"],
    )

    hyps, _ = await generate_with_debate(make_state(), count=1)

    assert len(hyps) == 1
    assert hyps[0].text == "converged idea"
    # Two free-form turns, then the structured turn - not the full budget.
    assert len(free_form) == 2
    assert len(finals) == 1


async def test_lowercase_hypothesis_prose_does_not_end_the_debate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ordinary talk about "the hypothesis" is not a termination signal."""
    turns = ["the hypothesis is weak"] * (DEBATE_MAX_TURNS - 1)
    free_form, finals = _stub_debate_llm_counting(monkeypatch, turns)

    await generate_with_debate(make_state(), count=1)

    assert len(free_form) == DEBATE_MAX_TURNS - 1
    assert len(finals) == 1


async def test_debate_produces_one_hypothesis_per_debate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each debate yields a DEBATE-method hypothesis with a unique debate id."""
    _stub_debate_llm(monkeypatch, "tumor suppressor X gates the pathway")
    hyps, transcripts = await generate_with_debate(make_state(), count=2)
    assert len(hyps) == 2
    assert all(h.text == "tumor suppressor X gates the pathway" for h in hyps)
    assert all(h.generation_method == GenerationMethod.DEBATE for h in hyps)
    assert all(h.experiment == "run the assay" for h in hyps)
    assert {h.debate_id for h in hyps} == {0, 1}
    assert len(transcripts) == 2
    assert transcripts[0]["hypothesis_text"] == (
        "tumor suppressor X gates the pathway"
    )


async def test_parallel_debates_receive_distinct_focus_prompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parallel debates are seeded with distinct angles to avoid collapse."""
    final_prompts: list[str] = []

    async def fake_call_llm(**_: Any) -> str:
        return "a debate turn argument"

    async def fake_call_llm_json(**kwargs: Any) -> dict[str, Any]:
        prompt = str(kwargs["prompt"])
        final_prompts.append(prompt)
        debate_number = len(final_prompts)
        return {
            "hypotheses": [
                {
                    "hypothesis": f"hypothesis from debate {debate_number}",
                    "explanation": "because the mechanism fits",
                    "literature_grounding": None,
                    "experiment": "run the assay",
                }
            ]
        }

    monkeypatch.setattr(debate, "call_llm", fake_call_llm)
    monkeypatch.setattr(debate, "call_llm_json", fake_call_llm_json)

    hyps, _ = await generate_with_debate(make_state(), count=3)

    assert [h.text for h in hyps] == [
        "hypothesis from debate 1",
        "hypothesis from debate 2",
        "hypothesis from debate 3",
    ]
    assert len(final_prompts) == 3
    assert "Parallel debate 1 of 3" in final_prompts[0]
    assert "Parallel debate 2 of 3" in final_prompts[1]
    assert "Parallel debate 3 of 3" in final_prompts[2]
    assert len(set(final_prompts)) == 3


async def test_empty_final_response_raises_generation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A final turn that returns no hypotheses surfaces a GenerationError."""

    async def fake_call_llm(**_: Any) -> str:
        return "turn"

    async def fake_call_llm_json(**_: Any) -> dict[str, Any]:
        return {"hypotheses": []}

    monkeypatch.setattr(debate, "call_llm", fake_call_llm)
    monkeypatch.setattr(debate, "call_llm_json", fake_call_llm_json)
    with pytest.raises(GenerationError):
        await generate_with_debate(make_state(), count=1)


async def test_generate_node_attaches_metrics_and_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """generate_node merges coordinator output with hypothesis-count metric."""

    async def fake_coordinator(_: Any) -> dict[str, Any]:
        # Mirrors the real coordinator's contract, which always includes
        # hypothesis_count alongside the hypotheses.
        return {
            "hypotheses": [
                make_hypothesis(text="h1"),
                make_hypothesis(text="h2"),
            ],
            "hypothesis_count": 2,
            "message": "generated 2 hypotheses",
        }

    monkeypatch.setattr(generate_mod, "generate_hypotheses", fake_coordinator)
    result = await generate_node(make_state())
    assert len(result["hypotheses"]) == 2
    assert result["metrics"].hypothesis_count == 2
