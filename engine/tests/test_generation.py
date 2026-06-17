"""Tests for debate-based generation and the generate_node wrapper.

``generate_with_debate`` runs multi-turn debates (each non-final turn calls
``call_llm`` and the final turn calls ``call_llm_json``) to produce one
Hypothesis per debate; these tests stub both LLM calls. ``generate_node`` is a
thin wrapper that delegates to the generation coordinator and attaches metrics.
"""

from typing import Any

import pytest

from co_scientist.exceptions import GenerationError
from co_scientist.models import GenerationMethod
from co_scientist.nodes import generate as generate_mod
from co_scientist.nodes.generate import generate_node
from co_scientist.nodes.generation import debate
from co_scientist.nodes.generation.debate import generate_with_debate
from tests._state import make_hypothesis, make_state


def _stub_debate_llm(monkeypatch: pytest.MonkeyPatch,
                     final_text: str) -> None:
    """Stub debate turns (call_llm) and the final hypothesis (call_llm_json)."""

    async def fake_call_llm(**_: Any) -> str:
        return "a debate turn argument"

    async def fake_call_llm_json(**_: Any) -> dict[str, Any]:
        return {
            "hypotheses": [{
                "hypothesis": final_text,
                "explanation": "because the mechanism fits",
                "literature_grounding": None,
                "experiment": "run the assay",
            }]
        }

    monkeypatch.setattr(debate, "call_llm", fake_call_llm)
    monkeypatch.setattr(debate, "call_llm_json", fake_call_llm_json)


async def test_count_zero_returns_empty() -> None:
    """Requesting zero debates short-circuits without any LLM call."""
    hyps, transcripts = await generate_with_debate(make_state(), count=0)
    assert hyps == []
    assert transcripts == []


async def test_debate_produces_one_hypothesis_per_debate(
        monkeypatch: pytest.MonkeyPatch) -> None:
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
        "tumor suppressor X gates the pathway")


async def test_empty_final_response_raises_generation_error(
        monkeypatch: pytest.MonkeyPatch) -> None:
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
        monkeypatch: pytest.MonkeyPatch) -> None:
    """generate_node merges coordinator output with a hypothesis-count metric."""

    async def fake_coordinator(_: Any) -> dict[str, Any]:
        return {
            "hypotheses": [make_hypothesis(text="h1"),
                           make_hypothesis(text="h2")],
            "message": "generated 2 hypotheses",
        }

    monkeypatch.setattr(generate_mod, "generate_hypotheses", fake_coordinator)
    result = await generate_node(make_state())
    assert len(result["hypotheses"]) == 2
    assert result["metrics"].hypothesis_count == 2
