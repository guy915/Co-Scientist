"""Tests for evolve_node: context-aware refinement of the top hypotheses.

The node's only external dependency is a per-hypothesis ``call_llm_json`` call
that returns the refined hypothesis. These tests stub that out and assert on the
deterministic top-k selection, the construction of evolved Hypothesis objects
from the canned response, and the recorded ``evolution_details``.

To keep the stub's evolved text below the 0.95 near-duplicate guard
(``DUPLICATE_SIMILARITY_THRESHOLD``) and distinct from each original, the input
hypotheses and the canned responses use disjoint vocabularies.
"""

from collections.abc import Callable
from typing import Any

import pytest

from co_scientist.nodes import evolve
from co_scientist.nodes.evolve import evolve_node
from tests._state import make_hypothesis, make_state


def _stub_llm(monkeypatch: pytest.MonkeyPatch,
              response: dict[str, Any]) -> None:
    """Patch evolve's call_llm_json to return one fixed response.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        response: The canned JSON response every evolution call receives.
    """

    async def fake(**_: Any) -> dict[str, Any]:
        return response

    monkeypatch.setattr(evolve, "call_llm_json", fake)


def _stub_llm_from_prompt(
        monkeypatch: pytest.MonkeyPatch,
        builder: Callable[[str], dict[str, Any]]) -> None:
    """Patch call_llm_json to derive each response from the prompt.

    The prompt embeds ``original_hypothesis``; ``builder`` maps the prompt text
    to a response dict, letting parallel evolutions return distinct text.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        builder: Callable taking the prompt string and returning a response.
    """

    async def fake(*, prompt: str, **_: Any) -> dict[str, Any]:
        return builder(prompt)

    monkeypatch.setattr(evolve, "call_llm_json", fake)


async def test_evolution_produces_evolved_hypotheses(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A canned response yields an evolved hypothesis and an evolution detail.

    The evolved hypothesis must take its text/explanation/experiment from the
    stub, and ``evolution_details`` must record the original->evolved
    transformation with the stub's refinement summary as the rationale.
    """
    original = make_hypothesis(text="quercetin inhibits aldolase activity",
                               explanation="old explanation",
                               experiment="old experiment")
    state = make_state(hypotheses=[original], evolution_max_count=1)
    _stub_llm(
        monkeypatch, {
            "hypothesis": "rapamycin suppresses mtor signaling downstream",
            "explanation": "fresh layman walkthrough",
            "experiment": "knock down the kinase and measure growth",
            "refinement_summary": "pivoted to a kinase mechanism",
        })

    result = await evolve_node(state)

    assert len(result["hypotheses"]) == 1
    evolved = result["hypotheses"][0]
    assert evolved.text == "rapamycin suppresses mtor signaling downstream"
    assert evolved.explanation == "fresh layman walkthrough"
    assert evolved.experiment == "knock down the kinase and measure growth"
    # The pre-evolution text is preserved in the hypothesis history.
    assert "quercetin inhibits aldolase activity" in evolved.evolution_history

    details = result["evolution_details"]
    assert len(details) == 1
    assert details[0]["original"] == "quercetin inhibits aldolase activity"
    assert details[0]["evolved"] == (
        "rapamycin suppresses mtor signaling downstream")
    assert details[0]["rationale"] == "pivoted to a kinase mechanism"


async def test_respects_evolution_max_count(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """With more hypotheses than the cap, only the top-k are evolved/kept.

    Five disjoint-vocabulary hypotheses with a cap of 2 must yield exactly two
    evolved hypotheses (the first two) and two evolution details; the lower
    ranked three are discarded.
    """
    texts = [
        "alpha membrane channel governs sodium",
        "bravo cytokine triggers inflammation cascade",
        "charlie enzyme catalyzes lipid breakdown",
        "delta receptor binds dopamine selectively",
        "echo transporter shuttles glucose intracellularly",
    ]
    hypotheses = [make_hypothesis(text=t) for t in texts]
    state = make_state(hypotheses=hypotheses, evolution_max_count=2)

    # Derive a distinct, disjoint evolved text per original so neither the
    # unchanged-guard nor the 0.95 near-duplicate guard fires.
    evolved_by_original = {
        "alpha membrane channel governs sodium":
            "foxtrot scaffold stabilizes microtubule assembly",
        "bravo cytokine triggers inflammation cascade":
            "golf ligand quenches reactive oxygen species",
    }

    def builder(prompt: str) -> dict[str, Any]:
        # Match the primary slot, not the truncated "other hypotheses" context
        # block where every sibling original also appears.
        for original, evolved in evolved_by_original.items():
            anchor = f"**Original Hypothesis:**\n{original}"
            if anchor in prompt:
                return {
                    "hypothesis": evolved,
                    "refinement_summary": f"refined: {evolved}",
                }
        raise AssertionError("evolution called for a non-top-k hypothesis")

    _stub_llm_from_prompt(monkeypatch, builder)

    result = await evolve_node(state)

    assert len(result["hypotheses"]) == 2
    assert len(result["evolution_details"]) == 2
    evolved_texts = {h.text for h in result["hypotheses"]}
    assert evolved_texts == {
        "foxtrot scaffold stabilizes microtubule assembly",
        "golf ligand quenches reactive oxygen species",
    }
    # None of the discarded lower-ranked originals survive.
    assert not (evolved_texts & set(texts))


async def test_empty_hypotheses_returns_empty(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """With no hypotheses, the node returns empty results without calling LLM."""

    async def never(**_: Any) -> dict[str, Any]:
        raise AssertionError("call_llm_json must not run with no hypotheses")

    monkeypatch.setattr(evolve, "call_llm_json", never)
    state = make_state(hypotheses=[], evolution_max_count=3)

    result = await evolve_node(state)

    assert result["hypotheses"] == []
    assert result["evolution_details"] == []


async def test_unchanged_response_records_no_evolution_detail(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """An LLM response echoing the original text records no evolution detail.

    The hypothesis is still kept (top-k survivor), but because the refined text
    equals the original, ``evolve_single_hypothesis`` returns ``None`` for the
    detail, so ``evolution_details`` is empty.
    """
    original = make_hypothesis(text="osmotic gradient drives water flux")
    state = make_state(hypotheses=[original], evolution_max_count=1)
    # Empty response -> ``hypothesis`` key missing, so the parser falls back to
    # the original text, which trips the unchanged-guard.
    _stub_llm(monkeypatch, {})

    result = await evolve_node(state)

    assert len(result["hypotheses"]) == 1
    assert result["hypotheses"][0].text == "osmotic gradient drives water flux"
    assert result["evolution_details"] == []
