"""The six Reflection review types (SSR §4) are enumerated and dispatchable."""

from co_scientist.nodes.review_types import (
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


def test_recurrent_review_adapts_full_review() -> None:
    """Recurrent review reuses the full-review schema with growing context."""
    assert prompt_name_for(ReviewType.RECURRENT) == "full_review"
