"""Coverage-focused tests for ``co_scientist.prompts.generation_debate``.

``test_prompts_generation.py`` already covers the mainline (no supervisor
guidance, no literature) paths for ``get_debate_generation_prompt``. This file
targets the branches it leaves uncovered: the supervisor-guidance formatting
helpers (key-areas-only, generation-phase-only, both-combined, and
neither-present), list-valued ``attributes``, and the literature-context
branch that injects ``articles_with_reasoning`` into the template variables.
"""

from co_scientist.prompts.generation_debate import (
    _build_debate_literature_variables,
    _format_debate_attributes,
    _format_supervisor_guidance_for_debate,
    get_debate_generation_prompt,
)
from co_scientist.prompts.loading import load_prompt

# --- _format_debate_attributes ----------------------------------------------


def test_format_debate_attributes_joins_list() -> None:
    """A list of attributes is comma-joined."""
    assert _format_debate_attributes(["novel", "testable"]) == "novel, testable"


def test_format_debate_attributes_empty_list_falls_back() -> None:
    """An empty list falls back to the default attributes phrase."""
    assert _format_debate_attributes([]) == "testable and falsifiable"


def test_format_debate_attributes_string_passthrough() -> None:
    """A plain string is returned unchanged."""
    assert _format_debate_attributes("bold") == "bold"


def test_format_debate_attributes_none_falls_back() -> None:
    """None falls back to the default attributes phrase."""
    assert _format_debate_attributes(None) == "testable and falsifiable"


# --- _format_supervisor_guidance_for_debate ---------------------------------


def test_supervisor_guidance_none_returns_empty() -> None:
    """A None supervisor_guidance yields an empty guidance section."""
    assert _format_supervisor_guidance_for_debate(None) == ""


def test_supervisor_guidance_non_dict_returns_empty() -> None:
    """A non-dict supervisor_guidance yields an empty guidance section."""
    guidance = _format_supervisor_guidance_for_debate(
        "not a dict"  # type: ignore[arg-type]
    )
    assert guidance == ""


def test_supervisor_guidance_populated_dict_with_no_relevant_keys() -> None:
    """A truthy dict with no research-goal/workflow-plan keys yields "".

    Exercises the body of the function (goal_analysis/workflow_plan
    extraction) without either sub-section producing content, so the final
    join-or-empty branch takes the empty path.
    """
    assert _format_supervisor_guidance_for_debate({"unrelated": "value"}) == ""


def test_supervisor_guidance_key_areas_only() -> None:
    """Key research areas alone render under their own header."""
    guidance = {
        "research_goal_analysis": {
            "key_areas": ["membrane biology", "signal transduction"]
        }
    }
    result = _format_supervisor_guidance_for_debate(guidance)
    assert "Key research areas to consider:" in result
    assert "- membrane biology" in result
    assert "- signal transduction" in result
    assert "Generation guidance:" not in result


def test_supervisor_guidance_generation_phase_only() -> None:
    """Generation-phase focus areas alone get their own header (needs_header).

    With no key areas, the generation-phase section owns the header (since
    no earlier section already introduced the guidance block).
    """
    guidance = {
        "workflow_plan": {
            "generation_phase": {"focus_areas": ["kinase inhibitors", "CNS"]}
        }
    }
    result = _format_supervisor_guidance_for_debate(guidance)
    assert "Generation guidance:" in result
    assert "Focus on: kinase inhibitors, CNS" in result
    assert "Key research areas" not in result


def test_supervisor_guidance_generation_phase_focus_areas_as_string() -> None:
    """A plain-string focus_areas value is used as-is (no join)."""
    guidance = {
        "workflow_plan": {
            "generation_phase": {"focus_areas": "receptor pharmacology"}
        }
    }
    result = _format_supervisor_guidance_for_debate(guidance)
    assert "Focus on: receptor pharmacology" in result


def test_supervisor_guidance_key_areas_and_generation_phase_combined() -> None:
    """With key areas present, the generation-phase section skips its header.

    The key-areas section already introduced the guidance block, so
    needs_header is False for the generation-phase section: only the "Focus
    on:" line appears, no second "Generation guidance:" header.
    """
    guidance = {
        "research_goal_analysis": {"key_areas": ["oncology"]},
        "workflow_plan": {"generation_phase": {"focus_areas": ["biomarkers"]}},
    }
    result = _format_supervisor_guidance_for_debate(guidance)
    assert "Key research areas to consider:" in result
    assert "- oncology" in result
    assert "Focus on: biomarkers" in result
    assert "Generation guidance:" not in result


def test_supervisor_guidance_generation_phase_without_focus_areas() -> None:
    """A generation_phase dict with no focus_areas key yields the empty str.

    generation_phase is truthy (non-empty dict) so the "not generation_phase"
    guard is skipped, but focus_areas is absent so no "Focus on:" line is
    appended and only the header line is produced (or nothing further).
    """
    guidance = {"workflow_plan": {"generation_phase": {"other_key": "x"}}}
    result = _format_supervisor_guidance_for_debate(guidance)
    assert "Generation guidance:" in result
    assert "Focus on:" not in result


# --- _build_debate_literature_variables -------------------------------------


def test_build_debate_literature_variables_includes_reasoning() -> None:
    """articles_with_reasoning is included in variables only when truthy."""
    variables = _build_debate_literature_variables(
        articles_with_reasoning="Synthesis of prior work.",
        articles=None,
        reference_list="",
    )
    assert variables["articles_with_reasoning"] == "Synthesis of prior work."


def test_build_debate_literature_variables_omits_reasoning_when_absent() -> (
    None
):
    """A None articles_with_reasoning leaves the key out of the dict."""
    variables = _build_debate_literature_variables(
        articles_with_reasoning=None,
        articles=None,
        reference_list="",
    )
    assert "articles_with_reasoning" not in variables


# --- get_debate_generation_prompt: end-to-end branch coverage --------------


def test_get_debate_generation_prompt_with_list_attributes() -> None:
    """List-valued attributes are comma-joined into the rendered prompt."""
    prompt, _schema = get_debate_generation_prompt(
        research_goal="engineer a drought-resistant crop",
        hypotheses_count=2,
        transcript="",
        attributes=["novel", "field-testable"],
    )
    assert "novel, field-testable" in prompt


def test_get_debate_generation_prompt_with_articles_with_reasoning() -> None:
    """Providing articles_with_reasoning selects the literature template.

    This both exercises the articles_with_reasoning branch in
    _build_debate_literature_variables and the prompt_name selection in
    get_debate_generation_prompt.
    """
    prompt, schema = get_debate_generation_prompt(
        research_goal="engineer a drought-resistant crop",
        hypotheses_count=2,
        transcript="prior turns",
        articles_with_reasoning="Prior work suggests ABA signaling matters.",
    )
    assert "Prior work suggests ABA signaling matters." in prompt
    # Unlike generation_after_debate.md, the literature template also has a
    # {{user_hypotheses}} placeholder this builder does not supply, so a
    # blanket "{{MISSING" check is not used here (same template-escaping
    # quirk noted in test_prompts_generation.py's paper-analysis tests).
    assert schema is None


def test_get_debate_generation_prompt_with_full_supervisor_guidance() -> None:
    """Supervisor guidance with both key areas and phase focus is embedded."""
    prompt, _schema = get_debate_generation_prompt(
        research_goal="engineer a drought-resistant crop",
        hypotheses_count=3,
        transcript="",
        supervisor_guidance={
            "research_goal_analysis": {"key_areas": ["osmotic stress"]},
            "workflow_plan": {
                "generation_phase": {"focus_areas": ["root architecture"]}
            },
        },
    )
    assert "osmotic stress" in prompt
    assert "root architecture" in prompt


def test_debate_prompt_does_not_force_clone_sentence_template() -> None:
    """The prompt must not impose the clone 'We want to develop X' format.

    The audit (E30/H15/K11) flagged the forced 'We want to develop [X] to
    enable [Y]' 2-3 sentence template as distorting mechanistic hypotheses.
    The final-turn instructions must instead ask for a domain-language
    mechanistic claim with a falsification criterion, and may only mention the
    old phrase to prohibit it.
    """
    prompt, _schema = get_debate_generation_prompt(
        research_goal="reduce cardiac senescence",
        hypotheses_count=1,
        transcript="prior turns",
    )
    # The phrase may appear only inside a negative instruction ("Do NOT ...").
    assert "to enable [Y]" not in prompt
    assert "2-3 sentences" not in prompt
    assert "mechanistic" in prompt.lower()
    assert "falsification" in prompt.lower()


def test_research_expansion_feedback_is_wired() -> None:
    """Research expansion re-runs generation informed by the meta-review.

    The mechanism is the meta-review context threaded into the generation
    prompts (consumed when the orchestrator re-enters generate in a later
    cycle), so assert the placeholder is present in the ``generation_after_
    debate`` prompt the research-expansion technique re-runs.
    """
    raw = load_prompt(
        "generation_after_debate",
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
