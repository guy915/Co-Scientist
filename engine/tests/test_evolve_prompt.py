"""Coverage-focused tests for ``co_scientist.agents.evolution.evolve_prompt``.

``test_evolve.py`` exercises ``evolve_node`` end to end but always passes an
empty ``meta_review`` and no ``supervisor_guidance`` (the ``make_state``
defaults), so the meta-review debug logging and the evolution-phase
supervisor-guidance formatting never run. This file calls the private
prompt-assembly helpers directly (matching the existing convention of testing
``reflection_helpers``'s private functions directly) to cover those branches,
plus the review-feedback formatter's "has reviews" path.
"""

from typing import Any

from co_scientist.agents.evolution.evolve_prompt import (
    _build_review_feedback,
    _build_supervisor_guidance_text,
    _format_evolution_guidance_lines,
    _format_iteration_strategy,
    _format_refinement_priorities,
    _log_meta_review_debug,
)
from co_scientist.models import HypothesisReview
from tests._state import make_hypothesis

# --- _log_meta_review_debug (covers _log_truncated_items/_log_items bodies) -


def test_log_meta_review_debug_with_all_fields_present() -> None:
    """A meta_review with every field populated logs without raising.

    Exercises the non-empty-items body of both _log_truncated_items (used
    for strengths/weaknesses) and _log_items (used for recommendations/
    themes); nothing to assert beyond "it runs to completion".
    """
    meta_review: dict[str, Any] = {
        "common_strengths": ["mechanistically grounded", "testable"],
        "common_weaknesses": ["under-specified controls"],
        "strategic_recommendations": ["broaden the biomarker panel"],
        "emerging_themes": ["convergence on kinase targets"],
    }
    _log_meta_review_debug(meta_review)  # Must not raise.


def test_log_meta_review_debug_with_empty_fields_is_a_noop() -> None:
    """An empty meta_review logs only the header lines, no item lists."""
    _log_meta_review_debug({})  # Must not raise.


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


# --- _format_refinement_priorities / _format_iteration_strategy ------------


def test_format_refinement_priorities_absent_returns_none() -> None:
    """No refinement_priorities key yields None."""
    assert _format_refinement_priorities({}) is None


def test_format_refinement_priorities_list_is_comma_joined() -> None:
    """A list of priorities is comma-joined into the guidance line."""
    result = _format_refinement_priorities(
        {"refinement_priorities": ["clarity", "safety"]}
    )
    assert result == "**Refinement Priorities:** clarity, safety\n"


def test_format_refinement_priorities_string_passthrough() -> None:
    """A plain-string priorities value is used as-is."""
    result = _format_refinement_priorities(
        {"refinement_priorities": "narrow the mechanism"}
    )
    assert result == "**Refinement Priorities:** narrow the mechanism\n"


def test_format_iteration_strategy_absent_returns_none() -> None:
    """No iteration_strategy key yields None."""
    assert _format_iteration_strategy({}) is None


def test_format_iteration_strategy_present() -> None:
    """A present iteration_strategy renders its guidance line."""
    result = _format_iteration_strategy(
        {"iteration_strategy": "converge on the top mechanism"}
    )
    assert result == ("**Iteration Strategy:** converge on the top mechanism\n")


# --- _format_evolution_guidance_lines ---------------------------------------


def test_format_evolution_guidance_lines_collects_both_sections() -> None:
    """Both formatters' output is collected when both fields are present."""
    lines = _format_evolution_guidance_lines(
        {
            "refinement_priorities": ["clarity"],
            "iteration_strategy": "converge",
        }
    )
    assert lines == [
        "**Refinement Priorities:** clarity\n",
        "**Iteration Strategy:** converge\n",
    ]


def test_format_evolution_guidance_lines_empty_when_neither_present() -> None:
    """Neither field present yields an empty list."""
    assert _format_evolution_guidance_lines({}) == []


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
