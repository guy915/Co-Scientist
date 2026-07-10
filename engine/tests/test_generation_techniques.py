"""The four generation techniques (SSR §4) are enumerated and dispatchable."""

from co_scientist.models import GenerationMethod
from co_scientist.nodes.generation.techniques import (
    GenerationTechnique,
    method_for,
    prompt_name_for,
)
from co_scientist.prompts.loading import load_prompt, load_prompt_with_schema

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
