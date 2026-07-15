"""The four generation techniques (SSR §4) are enumerated and dispatchable."""

from typing import Any

import pytest

from co_scientist.agents.generation.techniques import (
    GenerationTechnique,
    method_for,
    prompt_name_for,
)
from co_scientist.models import GenerationMethod
from co_scientist.prompts.loading import load_prompt, load_prompt_with_schema
from tests._state import make_state

_EXPECTED = {
    "literature_exploration",
    "simulated_debate",
    "assumptions_identification",
    "research_expansion",
}


def test_all_four_techniques_are_enumerated() -> None:
    assert {t.value for t in GenerationTechnique} == _EXPECTED


def test_generation_method_enum_covers_all_techniques() -> None:
    """Each technique records a distinct GenerationMethod on its hypotheses."""
    methods = {method_for(t) for t in GenerationTechnique}
    assert methods == {
        GenerationMethod.LITERATURE_TOOLS,
        GenerationMethod.DEBATE,
        GenerationMethod.ASSUMPTIONS,
        GenerationMethod.RESEARCH_EXPANSION,
    }


def test_every_technique_resolves_to_a_loadable_prompt() -> None:
    for technique in GenerationTechnique:
        name = prompt_name_for(technique)
        prompt = load_prompt(
            name,
            {
                "research_goal": "A goal",
                "domain_context": "",
                "meta_review_context": "",
                "num_hypotheses": 2,
                "tool_instructions": "",
                "hypotheses_so_far": "",
                "debate_transcript": "",
            },
        )
        assert prompt.strip()


def test_assumptions_technique_produces_hypotheses() -> None:
    """The new assumptions technique emits hypotheses directly."""
    _, schema = load_prompt_with_schema(
        "generation_assumptions",
        {
            "research_goal": "A goal",
            "domain_context": "",
            "meta_review_context": "",
            "num_hypotheses": 2,
        },
    )
    assert schema is not None
    assert "hypotheses" in schema["schema"]["properties"]


async def test_assumptions_grounds_in_supplied_literature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assumptions ingests literature context and resolves its citations (E07).

    When a reference index is supplied (literature-available run), the built
    prompt must carry the ``[C*]`` Citation Reference List so the technique can
    ground claims in real sources, and the resulting hypothesis's citation keys
    must resolve against those sources (previously the technique hardcoded an
    empty ``domain_context`` and an empty source map, so it could never ground).
    """
    from co_scientist.agents.generation import (
        assumptions as assumptions_mod,
    )
    from co_scientist.agents.generation.citations import (
        ReferenceIndex,
    )

    captured: dict[str, str] = {}

    async def _fake_call_llm_json(prompt: str, *_a: Any, **_k: Any) -> Any:
        captured["prompt"] = prompt
        return {
            "hypotheses": [
                {
                    "hypothesis": "A testable claim",
                    "explanation": "why",
                    "literature_grounding": "This builds on prior work [C1].",
                    "experiment": "how",
                }
            ]
        }

    monkeypatch.setattr(assumptions_mod, "call_llm_json", _fake_call_llm_json)

    reference_index = ReferenceIndex(
        text="[C1] Author et al. (2020). A relevant paper.",
        sources={"C1": {"title": "A relevant paper", "type": "paper"}},
    )
    state = make_state(
        research_goal="A goal",
        model_name="fake-model",
    )
    result = await assumptions_mod.generate_with_assumptions(
        state,
        1,
        articles_with_reasoning="literature synthesis text",
        reference_index=reference_index,
    )

    # The [C*] citation list reaches the assumptions prompt.
    assert "[C1]" in captured["prompt"]
    # The generated hypothesis's citation key resolves against the sources.
    assert result[0].citation_map
    assert "C1" in result[0].citation_map


def test_research_expansion_feedback_is_wired() -> None:
    """Research expansion re-runs generation informed by the meta-review.

    The mechanism is the meta-review context threaded into the generation
    prompts (consumed when the orchestrator re-enters generate in a later
    cycle), so assert the placeholder is present in the debate prompt the
    RESEARCH_EXPANSION technique maps to.
    """
    name = prompt_name_for(GenerationTechnique.RESEARCH_EXPANSION)
    raw = load_prompt(
        name,
        {
            "research_goal": "A goal",
            "domain_context": "",
            "meta_review_context": "META-REVIEW-FEEDBACK-MARKER",
            "num_hypotheses": 2,
            "hypotheses_so_far": "",
            "debate_transcript": "",
        },
    )
    # The meta-review feedback is substituted into the prompt (not dropped).
    assert "META-REVIEW-FEEDBACK-MARKER" in raw
