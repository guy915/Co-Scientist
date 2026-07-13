"""Tests for evolve_node: immutable-child refinement of the top hypotheses.

The node's only external dependency is a per-hypothesis ``call_llm_json`` call
that returns the refined hypothesis. These tests stub that out and assert on the
deterministic top-k selection, the construction of immutable child Hypothesis
objects (new id, parent link, Elo 1200, zero matches) from the canned response,
and the recorded ``evolution_details``.

evolve_node returns ``{"hypotheses": AppendHypotheses(children), ...}``: the
children are APPENDED to the pool by the reducer, and the parents are left
unchanged (paper invariant SSR §4, §12). Use ``_children`` to unwrap them.

To keep the stub's evolved text below the 0.95 near-duplicate guard
(``DUPLICATE_SIMILARITY_THRESHOLD``) and distinct from each original, the input
hypotheses and the canned responses use disjoint vocabularies.
"""

from collections.abc import Callable
from typing import Any

import pytest

from co_scientist.constants import INITIAL_ELO_RATING
from co_scientist.models import Hypothesis, HypothesisOrigin
from co_scientist.nodes import evolve
from co_scientist.nodes.evolve import _specialist_feedback_for, evolve_node
from tests._state import make_hypothesis, make_state


def _children(result: dict[str, Any]) -> list[Hypothesis]:
    """Return the evolution children an evolve_node result would append."""
    return list(result["hypotheses"].items)


def _stub_llm(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]
) -> None:
    """Patch evolve's call_llm_json to return one fixed response.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        response: The canned JSON response every evolution call receives.
    """

    async def fake(**_: Any) -> dict[str, Any]:
        return response

    monkeypatch.setattr(evolve, "call_llm_json", fake)


def test_specialist_feedback_joins_prior_agent_outputs() -> None:
    """Evolution receives debate, tournament, proximity, and probe feedback."""
    hypothesis = make_hypothesis(
        text="mitochondrial checkpoint controls neuronal aging",
        deep_verification_verdict="partially_holds",
        deep_verification_probes=[
            {"question": "Is it causal?", "answer": "Unknown"}
        ],
    )
    hypothesis.enrichments["claim_gate"] = {
        "decision": "block",
        "reason": "one causal claim lacks support",
    }
    state = make_state(
        hypotheses=[hypothesis],
        debate_transcripts=[
            {
                "debate_id": 3,
                "hypothesis_text": hypothesis.text,
                "transcript": "Skeptic requests a rescue experiment.",
            }
        ],
        tournament_matchups=[
            {
                "hypothesis_a_id": hypothesis.id,
                "hypothesis_b_id": "peer",
                "winner_id": "peer",
                "reasoning": "The peer has stronger causal controls.",
                "confidence": "high",
            }
        ],
        proximity_graph={
            "edges": [
                {
                    "source": hypothesis.id,
                    "target": "neighbor",
                    "similarity": 0.72,
                    "cluster_id": "c1",
                }
            ]
        },
    )

    feedback = _specialist_feedback_for(state, hypothesis)

    assert "rescue experiment" in feedback
    assert "stronger causal controls" in feedback
    assert '"outcome": "lost"' in feedback
    assert '"hypothesis_id": "neighbor"' in feedback
    assert "partially_holds" in feedback
    assert "one causal claim lacks support" in feedback


def _stub_llm_from_prompt(
    monkeypatch: pytest.MonkeyPatch, builder: Callable[[str], dict[str, Any]]
) -> None:
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A canned response yields an evolved hypothesis and an evolution detail.

    The evolved hypothesis must take its text/explanation/experiment from the
    stub, and ``evolution_details`` must record the original->evolved
    transformation with the stub's refinement summary as the rationale.
    """
    original = make_hypothesis(
        text="quercetin inhibits aldolase activity",
        explanation="old explanation",
        experiment="old experiment",
    )
    state = make_state(hypotheses=[original], evolution_max_count=1)
    _stub_llm(
        monkeypatch,
        {
            "hypothesis": "rapamycin suppresses mtor signaling downstream",
            "explanation": "fresh layman walkthrough",
            "experiment": "knock down the kinase and measure growth",
            "refinement_summary": "pivoted to a kinase mechanism",
        },
    )

    result = await evolve_node(state)

    children = _children(result)
    assert len(children) == 1
    child = children[0]
    assert child.text == "rapamycin suppresses mtor signaling downstream"
    assert child.explanation == "fresh layman walkthrough"
    assert child.experiment == "knock down the kinase and measure growth"
    # The child is a fresh, immutable entrant linked to its parent.
    assert child.id != original.id
    assert child.parent_id == original.id
    assert child.generation == 1
    assert child.origin is HypothesisOrigin.EVOLUTION
    assert child.elo_rating == INITIAL_ELO_RATING
    assert child.win_count == 0 and child.loss_count == 0
    assert child.reviews == []
    # The child's history records the parent's text; the parent is untouched.
    assert "quercetin inhibits aldolase activity" in child.evolution_history
    assert original.text == "quercetin inhibits aldolase activity"
    assert original.elo_rating == INITIAL_ELO_RATING

    details = result["evolution_details"]
    assert len(details) == 1
    assert details[0]["parent_id"] == original.id
    assert details[0]["child_id"] == child.id
    assert details[0]["original"] == "quercetin inhibits aldolase activity"
    assert details[0]["evolved"] == (
        "rapamycin suppresses mtor signaling downstream"
    )
    assert details[0]["rationale"] == "pivoted to a kinase mechanism"


async def test_evolution_child_starts_without_deep_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An evolution child is a fresh entrant with no deep-verification state.

    The child describes new text, so it starts with no probes/verdict and must
    be verified afresh. The parent keeps its own probes, untouched.
    """
    original = make_hypothesis(
        text="quercetin inhibits aldolase activity",
        deep_verification_probes=[
            {
                "question": "stale q",
                "answer": "stale a",
                "reasoning": "stale r",
                "assumption_is_fundamental": True,
            }
        ],
        deep_verification_verdict="holds",
    )
    state = make_state(hypotheses=[original], evolution_max_count=1)
    _stub_llm(
        monkeypatch,
        {
            "hypothesis": "rapamycin suppresses mtor signaling downstream",
            "explanation": "fresh layman walkthrough",
            "experiment": "knock down the kinase and measure growth",
            "refinement_summary": "pivoted to a kinase mechanism",
        },
    )

    result = await evolve_node(state)

    child = _children(result)[0]
    assert child.text == "rapamycin suppresses mtor signaling downstream"
    assert child.deep_verification_probes == []
    assert child.deep_verification_verdict is None
    # The parent's own probes are untouched.
    assert original.deep_verification_probes == [
        {
            "question": "stale q",
            "answer": "stale a",
            "reasoning": "stale r",
            "assumption_is_fundamental": True,
        }
    ]
    assert original.deep_verification_verdict == "holds"


async def test_evolution_noop_produces_no_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unchanged refinement creates NO child and leaves the parent intact.

    When the LLM returns no change, evolve_single_hypothesis rejects it: no
    child is minted, and the parent (with its probes) is untouched.
    """
    probes = [
        {
            "question": "q",
            "answer": "a",
            "reasoning": "r",
            "assumption_is_fundamental": False,
        }
    ]
    original = make_hypothesis(
        text="osmotic gradient drives water flux",
        deep_verification_probes=probes,
        deep_verification_verdict="holds",
    )
    state = make_state(hypotheses=[original], evolution_max_count=1)
    _stub_llm(monkeypatch, {})  # empty -> unchanged -> no child

    result = await evolve_node(state)

    assert _children(result) == []  # no fake child minted
    # The parent is untouched, probes intact.
    assert original.deep_verification_probes == probes
    assert original.deep_verification_verdict == "holds"


async def test_respects_evolution_max_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        "alpha membrane channel governs sodium": (
            "foxtrot scaffold stabilizes microtubule assembly"
        ),
        "bravo cytokine triggers inflammation cascade": (
            "golf ligand quenches reactive oxygen species"
        ),
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

    children = _children(result)
    assert len(children) == 2
    assert len(result["evolution_details"]) == 2
    evolved_texts = {h.text for h in children}
    assert evolved_texts == {
        "foxtrot scaffold stabilizes microtubule assembly",
        "golf ligand quenches reactive oxygen species",
    }
    # Only the top-2 were evolved; the children are new-text entrants and each
    # links back to one of the top-2 parents.
    assert not (evolved_texts & set(texts))
    top_two_ids = {hypotheses[0].id, hypotheses[1].id}
    assert {c.parent_id for c in children} == top_two_ids


async def test_empty_hypotheses_returns_no_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no hypotheses, node returns no children without calling LLM."""

    async def never(**_: Any) -> dict[str, Any]:
        raise AssertionError("call_llm_json must not run with no hypotheses")

    monkeypatch.setattr(evolve, "call_llm_json", never)
    state = make_state(hypotheses=[], evolution_max_count=3)

    result = await evolve_node(state)

    assert _children(result) == []
    assert result["evolution_details"] == []


async def test_unchanged_response_records_no_child_or_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An LLM response echoing the original text creates no child or detail.

    Because the refined text equals the original, ``evolve_single_hypothesis``
    rejects it: no child is appended and ``evolution_details`` is empty. The
    parent stays in the pool untouched.
    """
    original = make_hypothesis(text="osmotic gradient drives water flux")
    state = make_state(hypotheses=[original], evolution_max_count=1)
    # Empty response -> ``hypothesis`` key missing, so the parser falls back to
    # the original text, which trips the unchanged-guard.
    _stub_llm(monkeypatch, {})

    result = await evolve_node(state)

    assert _children(result) == []
    assert result["evolution_details"] == []
    assert original.text == "osmotic gradient drives water flux"
