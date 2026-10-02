"""Evolution prompt contracts for guidance, feedback, and diversity."""

from typing import Any

import pytest

from co_scientist.agents.evolution import EvolutionContext
from co_scientist.agents.evolution.evolution_operators import (
    EvolutionOperator,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _build_evolution_prompt,
    _build_review_feedback,
    _build_supervisor_guidance_text,
    _EvolutionOperation,
    _format_diversity_instruction,
    _format_partner_context,
)
from co_scientist.models import HypothesisReview
from co_scientist.offline.content import subject_terms
from tests._state import make_hypothesis, make_state

# --- _build_review_feedback --------------------------------------------------


def test_build_review_feedback_empty_when_no_reviews() -> None:
    """A hypothesis with no reviews yields an empty feedback string."""
    hypothesis = make_hypothesis(text="a hypothesis", reviews=[])
    assert _build_review_feedback(hypothesis) == ""


def test_build_review_feedback_renders_latest_review_as_json() -> None:
    """The most recent review's fields are rendered as indented JSON."""
    review = HypothesisReview(
        review_summary="Solid mechanism, weak controls.",
        scores={"novelty": 7, "rigor": 5},
        safety_ethical_concerns="None identified.",
        detailed_feedback={"novelty": "Reasonably fresh angle."},
        constructive_feedback="Add a dose-response arm.",
        overall_score=6.5,
    )
    hypothesis = make_hypothesis(text="a hypothesis", reviews=[review])

    feedback = _build_review_feedback(hypothesis)

    assert "Solid mechanism, weak controls." in feedback
    assert "Add a dose-response arm." in feedback
    assert '"novelty": 7' in feedback
    assert "6.5" in feedback


# --- _format_diversity_instruction ------------------------------------------


def test_diversity_instruction_short_text_not_marked_truncated() -> None:
    """Text under 200 chars renders without an appended "..." marker.

    Regression guard: the local bullet-list formatter this prompt used to
    carry appended "..." unconditionally, even to text it never truncated.
    """
    short_text = "a short hypothesis well under the 200-char cap"
    result = _format_diversity_instruction([short_text], [])
    assert short_text in result
    assert f"{short_text}..." not in result


def test_diversity_instruction_long_text_truncated_with_marker() -> None:
    """Text over 200 chars is cut to 200 chars with a "..." marker."""
    long_text = "x" * 250
    result = _format_diversity_instruction([long_text], [])
    assert ("x" * 200 + "...") in result
    assert long_text not in result


def test_diversity_instruction_empty_lists_render_none_provided() -> None:
    """No other hypotheses or removed duplicates renders "None provided".

    Regression guard: the local formatter this prompt used to carry
    returned "" on an empty list, which a caller-side ``or "None"``
    papered over with a bare "None" rather than the "None provided" every
    other prompt uses for an absent list.
    """
    result = _format_diversity_instruction([], [])
    assert "**Other hypotheses in the active pool:**\nNone provided" in result
    assert (
        "**Previously removed duplicates (DO NOT recreate these):**\n"
        "None provided" in result
    )


def test_combination_diversity_instruction_exempts_partners() -> None:
    """Combination exempts its partners from the stay-distinct rule.

    The result must stay distinct from non-partner hypotheses but is
    required to synthesize the designated partners, so the blanket
    "remain distinct from all" requirement is replaced.
    """
    result = _format_diversity_instruction(
        ["a peer hypothesis"],
        ["a removed duplicate"],
        EvolutionOperator.COMBINATION,
    )
    assert "MUST synthesize the designated" in result
    assert "designated partner" in result.replace("\n", " ")
    # The contradictory blanket "distinct from all" requirement is gone.
    assert "MUST remain DISTINCT from:\n1. All other hypotheses" not in result
    # Recreating removed duplicates stays forbidden.
    assert "NOT recreate any previously removed duplicate" in result


def test_non_combination_diversity_instruction_keeps_blanket_rule() -> None:
    """Every other operator still demands distinction from all peers."""
    result = _format_diversity_instruction(
        ["a peer hypothesis"], [], EvolutionOperator.ENHANCEMENT
    )
    assert "MUST remain DISTINCT from" in result


# --- _format_partner_context -------------------------------------------------


def test_partner_context_renders_full_fields_for_combination() -> None:
    """Combination partners render whole, never truncated."""
    partner = make_hypothesis(
        text="partner mechanism " + "x" * 300,
        explanation="a full explanation",
        literature_grounding="full grounding text",
        experiment="a full experiment design",
    )
    result = _format_partner_context((partner,), EvolutionOperator.COMBINATION)
    assert "## Combination Partners" in result
    assert "### Partner 1" in result
    assert partner.text in result  # untruncated
    assert "a full explanation" in result
    assert "full grounding text" in result
    assert "a full experiment design" in result
    assert "positional index" in result


def test_partner_context_inspiration_header() -> None:
    """Inspiration renders the same full fields under its own header."""
    partner = make_hypothesis(text="an existing top-ranked approach")
    result = _format_partner_context((partner,), EvolutionOperator.INSPIRATION)
    assert "## Inspiration Sources" in result
    assert partner.text in result


def test_partner_context_placeholder_for_other_operators() -> None:
    """Operators without partners render an explicit placeholder."""
    result = _format_partner_context((), EvolutionOperator.SIMPLIFICATION)
    assert "No partners are assigned" in result


def test_partner_context_empty_pool_for_combination() -> None:
    """A one-idea pool still renders the header with an empty note."""
    result = _format_partner_context((), EvolutionOperator.COMBINATION)
    assert "## Combination Partners" in result
    assert "No partners are available" in result


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        (
            {"refinement_priorities": ["clarity", "safety"]},
            "**Refinement Priorities:** clarity, safety\n",
        ),
        (
            {"refinement_priorities": "narrow the mechanism"},
            "**Refinement Priorities:** narrow the mechanism\n",
        ),
        (
            {"iteration_strategy": "converge on the top mechanism"},
            "**Iteration Strategy:** converge on the top mechanism\n",
        ),
    ],
)
def test_supervisor_guidance_formats_each_phase_field(
    phase: dict[str, Any],
    expected: str,
) -> None:
    """Evolution guidance preserves list/string priorities and strategy text."""
    result = _build_supervisor_guidance_text(
        {"workflow_plan": {"evolution_phase": phase}}
    )
    assert result == (
        "## Supervisor Guidance for Evolution\n"
        + expected
        + "\nUse this guidance to align your refinement with the research plan."
        + "\n"
    )


# --- _build_supervisor_guidance_text ----------------------------------------


def test_build_supervisor_guidance_text_none_returns_empty() -> None:
    """None supervisor_guidance yields an empty string."""
    assert _build_supervisor_guidance_text(None) == ""


def test_build_supervisor_guidance_text_no_evolution_phase_returns_empty() -> (
    None
):
    """A workflow_plan with no evolution_phase key yields an empty string."""
    assert _build_supervisor_guidance_text({"workflow_plan": {}}) == ""


def test_build_supervisor_guidance_text_renders_evolution_phase() -> None:
    """A populated evolution_phase renders the full guidance block."""
    guidance = {
        "workflow_plan": {
            "evolution_phase": {
                "refinement_priorities": ["clarity", "testability"],
                "iteration_strategy": "converge on the strongest mechanism",
            }
        }
    }
    result = _build_supervisor_guidance_text(guidance)
    assert "## Supervisor Guidance for Evolution" in result
    assert "**Refinement Priorities:** clarity, testability" in result
    assert (
        "**Iteration Strategy:** converge on the strongest mechanism" in result
    )
    assert "Use this guidance to align your refinement" in result


# --- _build_evolution_prompt: K3 novelty contract / K5 lab constraints ------


def _evolution_context(**state_overrides: Any) -> EvolutionContext:
    """A minimal evolution context carrying a full workflow state."""
    return EvolutionContext(
        model_name="test-model",
        meta_review={},
        removed_duplicates=[],
        state=make_state(**state_overrides),
    )


def test_evolution_prompt_hedges_novelty_claims() -> None:
    """Refinements must not assert definitive novelty (K3)."""
    prompt, _ = _build_evolution_prompt(
        make_hypothesis(text="the parent hypothesis"),
        ["a peer hypothesis"],
        _evolution_context(),
        _EvolutionOperation(),
    )
    assert "Novelty claims must be hedged" in prompt
    assert "to our knowledge" in prompt
    assert "{{MISSING" not in prompt


@pytest.mark.parametrize(
    "operator",
    [
        EvolutionOperator.COHERENCE_FEASIBILITY,
        EvolutionOperator.OUT_OF_BOX,
    ],
)
def test_published_templates_hedge_novelty_claims(
    operator: EvolutionOperator,
) -> None:
    """K3 applies to the two operators that render a published prompt.

    Their templates are separate files, so the hedging instruction has to
    be carried into each rather than inherited from evolution.md.
    """
    prompt, _ = _build_evolution_prompt(
        make_hypothesis(text="the parent hypothesis"),
        ["a peer hypothesis"],
        _evolution_context(),
        _EvolutionOperation(operator=operator),
    )
    assert "Novelty claims must be hedged" in prompt
    assert "to our knowledge" in prompt
    assert "{{MISSING" not in prompt


def test_feasibility_prompt_stays_on_topic_offline() -> None:
    """The offline backend must find the parent under A.6's own label.

    Published evolution-06 names the parent slot "Original
    Conceptualization", not "Original Hypothesis"; offline.content mines
    that slot for the run's subject terms, so a label it does not know
    silently degrades every offline feasibility refinement to generic
    prose while its siblings stay on topic.
    """
    prompt, _ = _build_evolution_prompt(
        make_hypothesis(text="pirfenidone suppresses myofibroblast activation"),
        [],
        _evolution_context(),
        _EvolutionOperation(operator=EvolutionOperator.COHERENCE_FEASIBILITY),
    )
    assert "pirfenidone" in subject_terms(prompt)


def test_evolution_prompt_renders_lab_constraints() -> None:
    """State lab constraints reach the feasibility guidance (K5)."""
    prompt, _ = _build_evolution_prompt(
        make_hypothesis(text="the parent hypothesis"),
        ["a peer hypothesis"],
        _evolution_context(lab_constraints=["No mammalian cell culture"]),
        _EvolutionOperation(),
    )
    assert "## Scientist's Lab Constraints" in prompt
    assert "No mammalian cell culture" in prompt


def test_evolution_prompt_unchanged_without_lab_constraints() -> None:
    """Empty constraints render no section and no MISSING sentinel (K5)."""
    prompt, _ = _build_evolution_prompt(
        make_hypothesis(text="the parent hypothesis"),
        ["a peer hypothesis"],
        _evolution_context(),
        _EvolutionOperation(),
    )
    assert "Lab Constraints" not in prompt
    assert "{{MISSING" not in prompt


# --- _build_evolution_prompt: MP-2 research goal ----------------------------


def test_evolution_prompt_includes_research_goal() -> None:
    """Published evolution prompts open with "Goal: {goal}" (MP-2).

    evolution-06-feasibility-improvement.md and
    evolution-07-out-of-the-box-thinking.md both open with the research
    goal; the template had no goal placeholder at all, so every evolved
    hypothesis was rewritten by a model never told what the run was for.
    """
    prompt, _ = _build_evolution_prompt(
        make_hypothesis(text="the parent hypothesis"),
        ["a peer hypothesis"],
        _evolution_context(
            research_goal="reverse MASH-associated liver fibrosis"
        ),
        _EvolutionOperation(),
    )
    assert "reverse MASH-associated liver fibrosis" in prompt
    assert "{{MISSING" not in prompt


# --- _build_evolution_prompt: MP-3 evaluation criteria/preferences ---------


def test_evolution_prompt_includes_preferences() -> None:
    """Published evolution prompts carry the scientist's criteria (MP-3).

    evolution-06 ("Evaluation Criteria: {preferences}") and evolution-07
    ("Criteria for a robust hypothesis: {preferences}") both surface the
    scientist's stated preferences to the refinement; ours dropped them
    entirely.
    """
    prompt, _ = _build_evolution_prompt(
        make_hypothesis(text="the parent hypothesis"),
        ["a peer hypothesis"],
        _evolution_context(
            preferences="prioritize wet-lab feasibility over novelty"
        ),
        _EvolutionOperation(),
    )
    assert "prioritize wet-lab feasibility over novelty" in prompt
    assert "{{MISSING" not in prompt


def test_evolution_prompt_defaults_preferences_when_absent() -> None:
    """Absent preferences fall back to the same default as generation's."""
    prompt, _ = _build_evolution_prompt(
        make_hypothesis(text="the parent hypothesis"),
        ["a peer hypothesis"],
        _evolution_context(),
        _EvolutionOperation(),
    )
    assert "Focus on novelty, testability, and potential impact." in prompt
