"""The six Reflection review types (SSR §4) are enumerated and dispatchable."""

import jsonschema

from co_scientist.agents.reflection.review_types import (
    ReviewType,
    prompt_name_for,
    schema_for,
)
from co_scientist.prompts.loading import load_prompt_with_schema

# The paper's six review types (SSR §4).
_EXPECTED = {
    "initial",
    "full",
    "deep_verification",
    "observation",
    "simulation",
    "recurrent",
}


def test_all_six_review_types_are_enumerated() -> None:
    assert {rt.value for rt in ReviewType} == _EXPECTED


def test_every_review_type_resolves_to_a_prompt_and_schema() -> None:
    """Each of the six types maps to a loadable prompt and a schema."""
    for review_type in ReviewType:
        name = prompt_name_for(review_type)
        schema = schema_for(review_type)
        assert schema is not None, f"{review_type} has no schema"
        # The prompt template loads (renders) without error.
        prompt, loaded_schema = load_prompt_with_schema(
            name,
            {
                "research_goal": "A goal",
                "hypothesis_text": "A hypothesis.",
                "domain_context": "",
                "tool_instructions": "",
            },
        )
        assert prompt.strip()
        assert loaded_schema == schema


def test_full_review_schema_shape() -> None:
    """The full review scores correctness/quality and surfaces assumptions."""
    schema = schema_for(ReviewType.FULL)
    assert schema is not None
    required = set(schema["schema"]["required"])
    assert {"correctness", "assumptions", "quality_and_novelty", "verdict"} <= (
        required
    )


def test_full_review_assumption_carries_published_reasoning() -> None:
    """Each assumption carries the published free-text reasoning (MO-9).

    docs/CORPUS-EXTRACTION.md, validated-outputs/kira6-detailed-output-
    validated.md -- 220 lines, sha256 b5a22b590874, "Reasoning about
    assumptions" -- prints a paragraph beside every assumption; the schema
    used to carry only the closed `support` enum.
    """
    schema = schema_for(ReviewType.FULL)
    assert schema is not None
    assumption = schema["schema"]["properties"]["assumptions"]["items"]
    assert set(assumption["required"]) == {"assumption", "reasoning", "support"}


def test_simulation_review_schema_shape() -> None:
    """The simulation review steps through the mechanism to a verdict."""
    schema = schema_for(ReviewType.SIMULATION)
    assert schema is not None
    props = schema["schema"]["properties"]
    assert props["verdict"]["enum"] == [
        "holds",
        "partially_holds",
        "breaks_down",
    ]
    assert "steps" in props and "failure_points" in props


# Both schemas below close the object (additionalProperties: False), so every
# answer the prompt asks for needs a property to land in. When one did not,
# the model invented a plausible name for it (`decisive_step`), validation
# rejected the whole response, and the node paid for a second full call --
# see the parity assertions that follow.
def test_simulation_review_answer_from_the_prompt_validates() -> None:
    """A response covering every numbered instruction fits the schema."""
    schema = schema_for(ReviewType.SIMULATION)
    assert schema is not None
    answer = {
        "model": "Two kinases coupled by a negative feedback loop.",
        "steps": [
            {"step": "The ligand binds its receptor.", "plausible": True}
        ],
        "failure_points": ["Step 3 stalls without the cofactor."],
        "robustness": "A redundant pathway blunts the effect.",
        "verdict": "partially_holds",
        "decisive_step": "Step 3.",
    }
    jsonschema.validate(instance=answer, schema=schema["schema"])


def test_full_review_answer_from_the_prompt_validates() -> None:
    """A response covering every numbered instruction fits the schema."""
    schema = schema_for(ReviewType.FULL)
    assert schema is not None
    answer = {
        "correctness": "Internally consistent.",
        "assumptions": [
            {
                "assumption": "The receptor is expressed.",
                "reasoning": "Two prior cohort studies detect it directly.",
                "support": "supported",
            }
        ],
        "quality_and_novelty": "A non-obvious combination.",
        "literature_grounding": "Two cohort studies report the association.",
        "verdict": "needs_revision",
        "justification": "The dose assumption is unsupported.",
    }
    jsonschema.validate(instance=answer, schema=schema["schema"])


def test_recurrent_review_adapts_full_review() -> None:
    """Recurrent review reuses the full-review schema with growing context."""
    assert prompt_name_for(ReviewType.RECURRENT) == "full_review"
