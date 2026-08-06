"""Tests for reflection_node: per-hypothesis literature analysis.

The node's only LLM dependency is ``call_llm_json``, which returns a
classification/reasoning dict per hypothesis; these tests stub that out and
assert on the reflection metadata written back onto each Hypothesis and the
returned state update. The INDRA/MCP enrichment path is left real: with the
default state's ``tool_registry=None`` it short-circuits to a network-free
no-op, which is exactly the LLM-only path under test.
"""

import pytest

from co_scientist.agents.reflection import reflection
from co_scientist.agents.reflection.reflection import reflection_node
from tests._llm_fake import stub_call_llm_json
from tests._state import make_hypothesis, make_state

# Literature context that satisfies the node's ``articles_with_reasoning``
# guard so reflection actually runs (an empty/None value short-circuits the
# whole node).
_ARTICLES = "Article 1: observation A supports pathway X."


async def test_empty_hypotheses_returns_empty() -> None:
    """With articles present but no hypotheses, the node returns cleanly.

    The articles guard is satisfied so the hypotheses guard is the one that
    fires; the node returns an empty dict and never calls the LLM.
    """
    state = make_state(hypotheses=[], articles_with_reasoning=_ARTICLES)
    result = await reflection_node(state)
    assert result == {}


async def test_missing_articles_skips_node() -> None:
    """Without articles_with_reasoning the node short-circuits to an empty dict.

    The default state leaves ``articles_with_reasoning`` as None, so reflection
    is skipped even when hypotheses are present.
    """
    state = make_state(hypotheses=[make_hypothesis(text="a hypothesis")])
    result = await reflection_node(state)
    assert result == {}


async def test_hypotheses_get_reflection_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each hypothesis gets reflection_notes built from the LLM response.

    The note interleaves the ``reasoning`` and ``classification`` keys read by
    ``analyze_single_hypothesis``; with no tool_registry the INDRA enrichment
    stays empty, so the ``indra_evidence`` key is never written.
    """
    hyp_a = make_hypothesis(text="alpha pathway drives growth")
    hyp_b = make_hypothesis(text="beta pathway drives growth")
    state = make_state(
        hypotheses=[hyp_a, hyp_b], articles_with_reasoning=_ARTICLES
    )
    stub_call_llm_json(
        monkeypatch,
        reflection,
        {
            "classification": "missing piece",
            "reasoning": "fills a gap",
        },
    )

    result = await reflection_node(state)

    returned = result["hypotheses"]
    expected_notes = "fills a gap\n\nClassification: missing piece"
    assert len(returned) == 2
    for hyp in returned:
        assert hyp.reflection_notes == expected_notes
        # LLM-only path: no INDRA enrichment was fetched.
        assert "indra_evidence" not in hyp.enrichments
    # The node mutates the same Hypothesis objects in place.
    assert hyp_a.reflection_notes == expected_notes
    assert hyp_b.reflection_notes == expected_notes
    # A reflection-phase assistant message is appended.
    assert result["messages"][0]["metadata"]["phase"] == "reflection"


async def test_empty_llm_response_defaults_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r"""An LLM response missing classification/reasoning uses safe defaults.

    ``analyze_single_hypothesis`` defaults ``classification`` to "neutral" and
    ``reasoning`` to "", so the note is exactly "\n\nClassification: neutral".
    """
    hyp = make_hypothesis(text="some hypothesis")
    state = make_state(hypotheses=[hyp], articles_with_reasoning=_ARTICLES)
    stub_call_llm_json(monkeypatch, reflection, {})

    result = await reflection_node(state)

    assert result["hypotheses"][0].reflection_notes == (
        "\n\nClassification: neutral"
    )
    assert "indra_evidence" not in result["hypotheses"][0].enrichments


async def test_positive_observations_accumulate_on_hypothesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirmed strengths are appended to the idea's stored notes (K8).

    The paper's observation review both critiques and confirms: positive
    observations are summarized and appended to the hypothesis. They land
    in reflection_notes -- the accumulated-feedback field the ranking
    prompts read -- ahead of the "Classification:" suffix that
    agents/ranking/ranking_prompt.py parses back out, and are recorded
    under enrichments["observation"].
    """
    hyp = make_hypothesis(text="alpha pathway drives growth")
    state = make_state(hypotheses=[hyp], articles_with_reasoning=_ARTICLES)
    stub_call_llm_json(
        monkeypatch,
        reflection,
        {
            "classification": "missing piece",
            "reasoning": "fills a gap",
            "positive_observations": ["explains the resistance phenotype"],
        },
    )

    result = await reflection_node(state)

    returned = result["hypotheses"][0]
    notes = returned.reflection_notes or ""
    assert "fills a gap" in notes
    assert "explains the resistance phenotype" in notes
    # The strengths accumulate ahead of the parseable classification suffix.
    assert notes.index("explains the resistance phenotype") < notes.index(
        "Classification: missing piece"
    )
    assert notes.endswith("Classification: missing piece")
    assert returned.enrichments["observation"]["positive_observations"] == [
        "explains the resistance phenotype"
    ]


async def test_no_positive_observations_keeps_notes_byte_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without confirmed strengths the notes are unchanged (no-op)."""
    hyp = make_hypothesis(text="alpha pathway drives growth")
    state = make_state(hypotheses=[hyp], articles_with_reasoning=_ARTICLES)
    stub_call_llm_json(
        monkeypatch,
        reflection,
        {"classification": "missing piece", "reasoning": "fills a gap"},
    )

    result = await reflection_node(state)

    returned = result["hypotheses"][0]
    assert returned.reflection_notes == (
        "fills a gap\n\nClassification: missing piece"
    )
    assert "positive_observations" not in returned.enrichments["observation"]


async def test_blank_positive_observations_are_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blank or whitespace-only positives never reach the notes."""
    hyp = make_hypothesis(text="alpha pathway drives growth")
    state = make_state(hypotheses=[hyp], articles_with_reasoning=_ARTICLES)
    stub_call_llm_json(
        monkeypatch,
        reflection,
        {
            "classification": "neutral",
            "reasoning": "no signal",
            "positive_observations": ["", "   "],
        },
    )

    result = await reflection_node(state)

    returned = result["hypotheses"][0]
    assert returned.reflection_notes == "no signal\n\nClassification: neutral"
    assert "positive_observations" not in returned.enrichments["observation"]


def test_observation_schema_bounds_positive_observations() -> None:
    """The positives field is a bounded optional string array (K8)."""
    from co_scientist.schemas.review import (
        REFLECTION_MAX_POSITIVE_OBSERVATIONS,
        REFLECTION_SCHEMA,
    )

    properties = REFLECTION_SCHEMA["schema"]["properties"]
    field = properties["positive_observations"]
    assert field["type"] == "array"
    assert field["items"] == {"type": "string"}
    assert field["maxItems"] == REFLECTION_MAX_POSITIVE_OBSERVATIONS
    assert (
        "positive_observations" not in REFLECTION_SCHEMA["schema"]["required"]
    )


def test_observation_prompt_asks_for_positive_observations() -> None:
    """The observation prompt instructs the model to confirm strengths."""
    from co_scientist.prompts import get_reflection_prompt

    prompt, _ = get_reflection_prompt(
        articles_with_reasoning="lit", hypothesis_text="H"
    )
    assert "Positive observations" in prompt
