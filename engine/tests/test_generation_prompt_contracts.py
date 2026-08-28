"""Prompt-contract tests for the generation family (audits K3/K5/K6/K7).

These pin the wording contracts the generation, validation, evolution, and
research-overview prompts now carry:

- K3: novelty claims must be hedged unless grounded in retrieved evidence,
  in every hypothesis-writing prompt and in the report-level overview.
- K5: the scientist's interview-elicited lab constraints render into the
  generation and evolution feasibility prompts, and render nothing when a
  run carries none.
- K6: the depth guidance (mechanism specificity, quantitative predictions,
  full experiment detail) is present wherever hypotheses or the overview
  are written.
- K7: the ``category`` field is required by the generation schemas and its
  value contract is presented in the prompt bodies.

The builders make no LLM or network calls, so the tests are deterministic.
"""

from typing import Any

import pytest

from co_scientist.prompts import (
    DraftPromptRequest,
    ValidationSynthesisRequest,
    format_lab_constraints_section,
    get_draft_prompt_with_tools,
    get_hypothesis_validation_synthesis_prompt,
    get_research_overview_prompt,
    get_validation_synthesis_prompt_with_tools,
)
from co_scientist.prompts.loading import load_prompt
from co_scientist.schemas.generation import (
    GENERATION_SCHEMA,
    HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA,
)
from tests._state import make_state

# The shared K3 contract: every hypothesis-writing prompt carries it, so a
# run can never be asked to assert definitive novelty without grounding.
# Matched case-insensitively: the overview template states it mid-sentence.
_NOVELTY_CONTRACT = "novelty claims must be hedged"
_HEDGED_EXAMPLE = "to our knowledge"


def _render_assumptions_prompt(state_overrides: dict[str, Any]) -> str:
    """Render the assumptions technique's final generation prompt.

    Mirrors ``assumptions._build_assumptions_prompt`` for the variables
    the contracts under test depend on, without an LLM call.
    """
    from co_scientist.agents.generation import assumptions as assumptions_mod

    state = make_state(**state_overrides)
    prompt, _ = assumptions_mod._build_assumptions_prompt(state, 2, "", "", "")
    return prompt


# --- K3: hedged novelty language --------------------------------------------


def test_assumptions_prompt_without_references_hedges_novelty() -> None:
    """Ungrounded generation still renders the hedged-novelty contract.

    The contract is a standing instruction, not a property of the run's
    retrieval: a degraded (no-literature) run is exactly the one whose
    novelty claims are least verified, so its prompt must carry the
    hedging language too.
    """
    prompt = _render_assumptions_prompt({})
    assert _NOVELTY_CONTRACT in prompt.lower()
    assert _HEDGED_EXAMPLE in prompt
    assert "bounded retrieval" in prompt


def test_draft_prompt_hedges_novelty() -> None:
    """The Phase 1 draft prompt carries the hedged-novelty contract."""
    prompt, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(research_goal="a goal", hypotheses_count=2)
    )
    assert _NOVELTY_CONTRACT in prompt.lower()
    assert "{{MISSING" not in prompt


def test_validation_synthesis_prompts_hedge_novelty() -> None:
    """Both validation-synthesis variants carry the hedged-novelty contract."""
    analyses: list[dict[str, Any]] = []
    plain = get_hypothesis_validation_synthesis_prompt(
        research_goal="a goal", hypotheses_with_analyses=analyses
    )
    with_tools, _ = get_validation_synthesis_prompt_with_tools(
        ValidationSynthesisRequest(
            research_goal="a goal", hypotheses_with_analyses=analyses
        )
    )
    assert _NOVELTY_CONTRACT in plain.lower()
    assert _NOVELTY_CONTRACT in with_tools.lower()


def test_evolution_prompt_hedges_novelty() -> None:
    """The evolution template carries the hedged-novelty contract."""
    prompt = load_prompt("evolution", {})
    assert _NOVELTY_CONTRACT in prompt.lower()


def test_research_overview_prompt_hedges_novelty() -> None:
    """The report-level overview must not assert definitive novelty."""
    prompt, _ = get_research_overview_prompt(
        research_goal="a goal", hypotheses_summary="1. an idea"
    )
    assert _NOVELTY_CONTRACT in prompt.lower()
    assert "report-level text" in prompt


# --- K6: depth guidance -------------------------------------------------------


def test_assumptions_prompt_carries_depth_requirements() -> None:
    """Assumption-driven generation is instructed to write at full depth."""
    prompt = _render_assumptions_prompt({})
    assert "## Depth Requirements" in prompt
    assert "Mechanism specificity" in prompt
    assert "Quantitative predictions" in prompt
    assert "Complete experiment detail" in prompt


def test_draft_prompt_requires_full_depth_drafts() -> None:
    """Drafts must be written at full depth: they become final hypotheses."""
    prompt, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(research_goal="a goal", hypotheses_count=2)
    )
    assert "a shallow draft becomes a shallow final hypothesis" in prompt


def test_research_overview_prompt_carries_depth_guidance() -> None:
    """The overview is a research strategy document, not an abstract."""
    prompt, _ = get_research_overview_prompt(
        research_goal="a goal", hypotheses_summary="1. an idea"
    )
    assert "research strategy document" in prompt
    assert "multi-paragraph narrative" in prompt


def test_research_overview_prompt_asks_for_sub_topics() -> None:
    """MO-1: the prompt must ask for the nested sub-topic layer."""
    prompt, _ = get_research_overview_prompt(
        research_goal="a goal", hypotheses_summary="1. an idea"
    )
    assert "sub_topics" in prompt
    assert "specific_questions" in prompt


def test_research_overview_prompt_asks_for_recent_findings() -> None:
    """MO-12: the prompt must ask for the "what is already known" slot."""
    prompt, _ = get_research_overview_prompt(
        research_goal="a goal", hypotheses_summary="1. an idea"
    )
    assert "recent_findings" in prompt
    assert "already established" in prompt


def test_generation_schema_fields_ask_for_depth() -> None:
    """The shared explanation/experiment fields no longer cap brevity."""
    properties = GENERATION_SCHEMA["schema"]["properties"]["hypotheses"][
        "items"
    ]["properties"]
    assert "(4-6 sentences)" not in properties["explanation"]["description"]
    assert "(4-6 sentences)" not in properties["experiment"]["description"]
    assert "Depth over brevity" in properties["explanation"]["description"]
    assert "Depth over brevity" in properties["experiment"]["description"]


# --- K7: required, prompt-present category -----------------------------------


def test_generation_schemas_require_category() -> None:
    """Category is required in both generation schemas that carry it."""
    generation_item = GENERATION_SCHEMA["schema"]["properties"]["hypotheses"][
        "items"
    ]
    synthesis_item = HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA["schema"][
        "properties"
    ]["hypotheses"]["items"]
    assert "category" in generation_item["required"]
    assert "category" in synthesis_item["required"]


def test_assumptions_prompt_presents_category_contract() -> None:
    """The assumptions prompt names the category values and selection rule."""
    prompt = _render_assumptions_prompt({})
    assert "## Category Label" in prompt
    assert "2-4 word" in prompt
    assert "Every hypothesis must carry a category" in prompt


def test_validation_synthesis_prompts_present_category() -> None:
    """Both synthesis prompts present the category field and its contract."""
    analyses: list[dict[str, Any]] = []
    plain = get_hypothesis_validation_synthesis_prompt(
        research_goal="a goal", hypotheses_with_analyses=analyses
    )
    with_tools, _ = get_validation_synthesis_prompt_with_tools(
        ValidationSynthesisRequest(
            research_goal="a goal", hypotheses_with_analyses=analyses
        )
    )
    for prompt in (plain, with_tools):
        assert "category" in prompt
        assert "mechanism family" in prompt


# --- MO-6: required, prompt-present scene-setting -----------------------------


def test_generation_schemas_require_scene_setting() -> None:
    """introduction/recent_findings are required in both generation schemas."""
    generation_item = GENERATION_SCHEMA["schema"]["properties"]["hypotheses"][
        "items"
    ]
    synthesis_item = HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA["schema"][
        "properties"
    ]["hypotheses"]["items"]
    for node in (generation_item, synthesis_item):
        assert "introduction" in node["required"]
        assert "recent_findings" in node["required"]


def test_assumptions_prompt_presents_scene_setting_contract() -> None:
    """The assumptions prompt names both scene-setting fields."""
    prompt = _render_assumptions_prompt({})
    assert "## Scene-Setting" in prompt
    assert "introduction" in prompt
    assert "recent_findings" in prompt


def test_validation_synthesis_prompts_present_scene_setting() -> None:
    """Both synthesis prompts present the scene-setting fields."""
    analyses: list[dict[str, Any]] = []
    plain = get_hypothesis_validation_synthesis_prompt(
        research_goal="a goal", hypotheses_with_analyses=analyses
    )
    with_tools, _ = get_validation_synthesis_prompt_with_tools(
        ValidationSynthesisRequest(
            research_goal="a goal", hypotheses_with_analyses=analyses
        )
    )
    for prompt in (plain, with_tools):
        assert "introduction" in prompt
        assert "recent_findings" in prompt


# --- MO-10: required, prompt-present safety and toxicity ----------------------


def test_generation_schemas_require_safety_and_toxicity() -> None:
    """safety_and_toxicity is required in both generation schemas."""
    generation_item = GENERATION_SCHEMA["schema"]["properties"]["hypotheses"][
        "items"
    ]
    synthesis_item = HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA["schema"][
        "properties"
    ]["hypotheses"]["items"]
    for node in (generation_item, synthesis_item):
        assert "safety_and_toxicity" in node["required"]


def test_assumptions_prompt_presents_safety_and_toxicity_contract() -> None:
    """The assumptions prompt names the safety_and_toxicity field."""
    prompt = _render_assumptions_prompt({})
    assert "## Safety and Toxicity" in prompt
    assert "safety_and_toxicity" in prompt


def test_validation_synthesis_prompts_present_safety_and_toxicity() -> None:
    """Both synthesis prompts present the safety_and_toxicity field."""
    analyses: list[dict[str, Any]] = []
    plain = get_hypothesis_validation_synthesis_prompt(
        research_goal="a goal", hypotheses_with_analyses=analyses
    )
    with_tools, _ = get_validation_synthesis_prompt_with_tools(
        ValidationSynthesisRequest(
            research_goal="a goal", hypotheses_with_analyses=analyses
        )
    )
    for prompt in (plain, with_tools):
        assert "safety_and_toxicity" in prompt


# --- K5: lab constraints section ----------------------------------------------


def test_lab_constraints_section_empty_when_no_constraints() -> None:
    """No constraints render nothing, leaving the prompt unchanged."""
    assert format_lab_constraints_section(None) == ""
    assert format_lab_constraints_section([]) == ""


def test_lab_constraints_section_renders_constraints() -> None:
    """Constraints render as a feasibility-respecting section."""
    section = format_lab_constraints_section(
        ["No mouse work; zebrafish only", "Budget capped at $50k"]
    )
    assert "## Scientist's Lab Constraints" in section
    assert "No mouse work; zebrafish only" in section
    assert "Budget capped at $50k" in section
    assert "Respect them" in section


def test_assumptions_prompt_renders_lab_constraints_from_state() -> None:
    """State lab constraints reach the prompt; absent renders none."""
    with_constraints = _render_assumptions_prompt(
        {"lab_constraints": ["Zebrafish facility only"]}
    )
    assert "## Scientist's Lab Constraints" in with_constraints
    assert "Zebrafish facility only" in with_constraints

    without = _render_assumptions_prompt({})
    assert "Lab Constraints" not in without


def test_draft_prompt_renders_lab_constraints() -> None:
    """The draft request's lab constraints render; the default renders none."""
    prompt, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(
            research_goal="a goal",
            hypotheses_count=2,
            lab_constraints=["Biosafety level 2 only"],
        )
    )
    assert "Biosafety level 2 only" in prompt
    assert "{{MISSING" not in prompt

    bare, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(research_goal="a goal", hypotheses_count=2)
    )
    assert "Lab Constraints" not in bare
    assert "{{MISSING" not in bare


@pytest.mark.parametrize(
    "overrides",
    [{}, {"lab_constraints": ["No primate work"]}],
)
def test_assumptions_prompt_fully_interpolated(
    overrides: dict[str, Any],
) -> None:
    """The new placeholders never leak a MISSING sentinel."""
    prompt = _render_assumptions_prompt(overrides)
    assert "{{MISSING" not in prompt
