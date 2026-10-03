"""Tests for supervisor guidance reaching the two generation writers.

The supervisor synthesizes a per-run config and the writers are supposed to
read their own slice of it: the shared ``preferences`` list plus the
instruction list written for that writer's mode. These tests pin that each
writer gets its own list and not the other's, and that the draft writer gets
a guidance block at all -- it read a key no run ever produced, so it was
handed an empty block on every real run.
"""

from co_scientist.prompts import (
    DraftPromptRequest,
    PromptRunContext,
    get_draft_prompt_with_tools,
)
from co_scientist.prompts.generation_debate import (
    _format_supervisor_guidance_for_debate,
)
from co_scientist.prompts.generation_draft import (
    format_supervisor_guidance_for_generation,
)

# A supervisor_guidance dict shaped the way agents/supervisor/supervisor.py
# assembles it, carrying an instruction list for each writer mode.
_GUIDANCE = {
    "research_goal_analysis": {"key_areas": ["oncology"]},
    "workflow_plan": {"generation_phase": {"focus_areas": ["biomarkers"]}},
    "config_synthesis": {
        "preferences": ["testable within two years"],
        "draft_instructions": ["anchor each idea in a reported result"],
        "debate_instructions": ["attack the weakest causal link"],
        "review_instructions": ["penalize restatements of known biology"],
    },
}

# --- format_supervisor_guidance_for_generation ------------------------------


def test_draft_guidance_renders_the_plan_rather_than_nothing() -> None:
    """The draft writer sees the supervisor's focus areas and preferences.

    Regression: this formatter read a free-text "research_plan" key, which
    is what the streamed output payload renames supervisor_guidance to --
    not a field inside it -- so it returned "" on every real run.
    """
    result = format_supervisor_guidance_for_generation(_GUIDANCE)

    assert "## Supervisor Guidance for Generation" in result
    assert "**Focus on:** biomarkers" in result
    assert "- testable within two years" in result


def test_draft_guidance_carries_only_the_drafting_instructions() -> None:
    """Each writer mode gets its own list, never a sibling mode's."""
    result = format_supervisor_guidance_for_generation(_GUIDANCE)

    assert "anchor each idea in a reported result" in result
    assert "attack the weakest causal link" not in result
    assert "penalize restatements of known biology" not in result


def test_draft_guidance_bullets_a_bare_string_as_one_item() -> None:
    """A string where the schema declares an array is one bullet, not many.

    Production runs on a provider whose json_object mode does not enforce
    the schema, so a bare string arrives; iterating it would bullet every
    character.
    """
    guidance = {"config_synthesis": {"preferences": "must be falsifiable"}}

    result = format_supervisor_guidance_for_generation(guidance)

    assert "- must be falsifiable\n" in result
    assert "- m\n" not in result


def test_draft_guidance_is_empty_without_a_plan() -> None:
    """Nothing to say renders nothing, not a bare header."""
    assert format_supervisor_guidance_for_generation(None) == ""
    assert format_supervisor_guidance_for_generation({}) == ""
    assert format_supervisor_guidance_for_generation({"unrelated": 1}) == ""


def test_draft_guidance_survives_a_scalar_where_an_object_belongs() -> None:
    """An unenforced schema can answer an object field with a scalar."""
    assert (
        format_supervisor_guidance_for_generation(
            {"workflow_plan": {"generation_phase": "focus on kinases"}}
        )
        == ""
    )
    assert (
        format_supervisor_guidance_for_generation(
            {"workflow_plan": "draft broadly", "config_synthesis": "be bold"}
        )
        == ""
    )


# --- _format_supervisor_guidance_for_debate ---------------------------------


def test_debate_guidance_carries_only_the_debate_instructions() -> None:
    """The debate writer reads preferences plus its own instruction list."""
    result = _format_supervisor_guidance_for_debate(_GUIDANCE)

    assert "- testable within two years" in result
    assert "attack the weakest causal link" in result
    assert "anchor each idea in a reported result" not in result


def test_debate_guidance_keeps_its_existing_plan_sections() -> None:
    """The config slice is added to the key-areas/focus sections, not over."""
    result = _format_supervisor_guidance_for_debate(_GUIDANCE)

    assert "Key research areas to consider:" in result
    assert "Focus on: biomarkers" in result


def test_debate_guidance_renders_config_alone() -> None:
    """A run whose plan carries only a config still reaches the writer."""
    guidance = {
        "config_synthesis": {"debate_instructions": ["contest the framing"]}
    }

    result = _format_supervisor_guidance_for_debate(guidance)

    assert "contest the framing" in result


# --- end to end -------------------------------------------------------------


def test_the_drafting_writer_actually_receives_the_guidance() -> None:
    """The block reaches the rendered prompt, not just its formatter."""
    prompt, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(
            research_goal="find a new target in fibrosis",
            hypotheses_count=3,
            context=PromptRunContext(supervisor_guidance=_GUIDANCE),
        )
    )

    assert "anchor each idea in a reported result" in prompt
    assert "attack the weakest causal link" not in prompt
    assert "{{MISSING" not in prompt
