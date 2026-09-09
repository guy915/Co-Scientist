"""The six Reflection review types (SSR §4) are enumerated and dispatchable."""

import pathlib

import jsonschema

from co_scientist.agents.reflection.review_types import (
    ReviewType,
    prompt_name_for,
    schema_for,
)
from co_scientist.prompts.loading import load_prompt_with_schema
from co_scientist.schemas.review import FULL_REVIEW_SCHEMA

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
        "comparison_with_knowledge_base": "Agrees with the canonical model.",
        "goal_requirements_assessment": "Meets every stated requirement.",
        "feasibility_steps": ["Run the pilot cohort.", "Read out at day 30."],
        "feasibility_reasoning": "Both steps use standard assays.",
        "impact_assessment": "Would change first-line practice.",
        "reviews_summary": {
            "executive_verdict": "The hypothesis stands, with one caveat.",
            "critical_flaws": ["The dose assumption is unsupported."],
            "addressed_objections": ["Off-target binding is ruled out."],
            "validated_risks": ["The effect may be strain-specific."],
            "supporting_arguments": ["Two cohorts show the association."],
            "alignment_and_novelty": ["Squarely on the research goal."],
            "feasibility_assessment": ["A pilot settles it in six weeks."],
            "conclusion": "Worth a pilot once the dose is pinned down.",
        },
        "verdict": "needs_revision",
        "justification": "The dose assumption is unsupported.",
    }
    jsonschema.validate(instance=answer, schema=schema["schema"])


def test_full_review_prompt_names_every_required_field() -> None:
    """A required field the prompt never mentions is never filled.

    ``reviews_summary`` was declared, optional, and unnamed by
    ``full_review.md``, so nothing ever asked a model for it. Requiring
    it fixes nothing on its own -- on a provider that enforces the
    schema, a field the prompt never asks for makes a prompt-faithful
    answer fail validation and buys the same review a second time.
    Required and named are one change, and this pins them together for
    every required field the schema declares.
    """
    schema = schema_for(ReviewType.FULL)
    assert schema is not None
    template = load_prompt_with_schema(
        "full_review",
        {
            "research_goal": "A goal",
            "hypothesis_text": "A hypothesis.",
            "domain_context": "",
            "tool_instructions": "",
        },
    )[0]
    unnamed = [
        field
        for field in schema["schema"]["required"]
        if f"`{field}`" not in template
    ]
    assert not unnamed, f"full_review.md does not name {unnamed}"


def test_full_review_prompt_names_every_reviews_summary_part() -> None:
    """The eight published parts are asked for by name, not by schema alone.

    ``reviews_summary`` is a closed object whose parts appeared nowhere
    but the schema block appended to the prompt -- the same shape that
    made the ranking judge invent a key of its own.
    """
    node = FULL_REVIEW_SCHEMA["schema"]["properties"]["reviews_summary"]
    template = (
        pathlib.Path(__file__).resolve().parents[1]
        / "src"
        / "co_scientist"
        / "prompts"
        / "templates"
        / "full_review.md"
    ).read_text()
    for part in node["properties"]:
        assert f"`{part}`" in template, part


def test_recurrent_review_adapts_full_review() -> None:
    """Recurrent review reuses the full-review schema with growing context."""
    assert prompt_name_for(ReviewType.RECURRENT) == "full_review"
