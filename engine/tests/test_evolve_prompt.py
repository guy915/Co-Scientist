from __future__ import annotations

from typing import Any

import pytest

from co_scientist.agents.evolution import EvolutionContext, evolve
from co_scientist.agents.evolution.evolve import evolve_single_hypothesis
from co_scientist.agents.evolution.evolve_prompt import (
    EvolutionOperator,
    _build_evolution_prompt,
    _build_review_feedback,
    _build_supervisor_guidance_text,
    _EvolutionOperation,
    _format_diversity_instruction,
    _format_partner_context,
    operator_instruction,
    operator_template,
    select_operators,
)
from co_scientist.models import HypothesisReview
from co_scientist.offline.llm import subject_terms
from tests._state import make_hypothesis, make_state


def test_build_review_feedback_empty_when_no_reviews() -> None:
    hypothesis = make_hypothesis(text="a hypothesis", reviews=[])
    assert _build_review_feedback(hypothesis) == ""


def test_build_review_feedback_renders_latest_review_as_json() -> None:
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


def test_diversity_instruction_short_text_not_marked_truncated() -> None:
    short_text = "a short hypothesis well under the 200-char cap"
    result = _format_diversity_instruction([short_text], [])
    assert short_text in result
    assert f"{short_text}..." not in result


def test_diversity_instruction_long_text_truncated_with_marker() -> None:
    long_text = "x" * 250
    result = _format_diversity_instruction([long_text], [])
    assert ("x" * 200 + "...") in result
    assert long_text not in result


def test_diversity_instruction_empty_lists_render_none_provided() -> None:
    result = _format_diversity_instruction([], [])
    assert "**Other hypotheses in the active pool:**\nNone provided" in result
    assert (
        "**Previously removed duplicates (DO NOT recreate these):**\n"
        "None provided" in result
    )


def test_combination_diversity_instruction_exempts_partners() -> None:
    """Synthesis requires overlap with designated partners while staying
    distinct from other peers."""
    result = _format_diversity_instruction(
        ["a peer hypothesis"],
        ["a removed duplicate"],
        EvolutionOperator.COMBINATION,
    )
    assert "MUST synthesize the designated" in result
    assert "designated partner" in result.replace("\n", " ")
    assert "MUST remain DISTINCT from:\n1. All other hypotheses" not in result
    assert "NOT recreate any previously removed duplicate" in result


def test_non_combination_diversity_instruction_keeps_blanket_rule() -> None:
    """Synthesis requires overlap with designated partners while staying
    distinct from other peers."""
    result = _format_diversity_instruction(
        ["a peer hypothesis"], [], EvolutionOperator.ENHANCEMENT
    )
    assert "MUST remain DISTINCT from" in result


def test_partner_context_renders_full_fields_for_combination() -> None:
    partner = make_hypothesis(
        text="partner mechanism " + "x" * 300,
        explanation="a full explanation",
        literature_grounding="full grounding text",
        experiment="a full experiment design",
    )
    result = _format_partner_context((partner,), EvolutionOperator.COMBINATION)
    assert "## Combination Partners" in result
    assert "### Partner 1" in result
    assert partner.text in result
    assert "a full explanation" in result
    assert "full grounding text" in result
    assert "a full experiment design" in result
    assert "positional index" in result


def test_partner_context_inspiration_header() -> None:
    partner = make_hypothesis(text="an existing top-ranked approach")
    result = _format_partner_context((partner,), EvolutionOperator.INSPIRATION)
    assert "## Inspiration Sources" in result
    assert partner.text in result


def test_partner_context_placeholder_for_other_operators() -> None:
    result = _format_partner_context((), EvolutionOperator.SIMPLIFICATION)
    assert "No partners are assigned" in result


def test_partner_context_empty_pool_for_combination() -> None:
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
    result = _build_supervisor_guidance_text(
        {"workflow_plan": {"evolution_phase": phase}}
    )
    assert result == (
        "## Supervisor Guidance for Evolution\n"
        + expected
        + "\nUse this guidance to align your refinement with the research plan."
        + "\n"
    )


def test_build_supervisor_guidance_text_none_returns_empty() -> None:
    assert _build_supervisor_guidance_text(None) == ""


def test_build_supervisor_guidance_text_no_evolution_phase_returns_empty() -> (
    None
):
    assert _build_supervisor_guidance_text({"workflow_plan": {}}) == ""


def test_build_supervisor_guidance_text_renders_evolution_phase() -> None:
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


def _evolution_context(**state_overrides: Any) -> EvolutionContext:
    return EvolutionContext(
        model_name="test-model",
        meta_review={},
        removed_duplicates=[],
        state=make_state(**state_overrides),
    )


def test_evolution_prompt_hedges_novelty_claims() -> None:
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
    """The offline miner must recognize the parent label or refinements lose
    the run subject."""
    prompt, _ = _build_evolution_prompt(
        make_hypothesis(text="pirfenidone suppresses myofibroblast activation"),
        [],
        _evolution_context(),
        _EvolutionOperation(operator=EvolutionOperator.COHERENCE_FEASIBILITY),
    )
    assert "pirfenidone" in subject_terms(prompt)


def test_evolution_prompt_renders_lab_constraints() -> None:
    prompt, _ = _build_evolution_prompt(
        make_hypothesis(text="the parent hypothesis"),
        ["a peer hypothesis"],
        _evolution_context(lab_constraints=["No mammalian cell culture"]),
        _EvolutionOperation(),
    )
    assert "## Scientist's Lab Constraints" in prompt
    assert "No mammalian cell culture" in prompt


def test_evolution_prompt_unchanged_without_lab_constraints() -> None:
    prompt, _ = _build_evolution_prompt(
        make_hypothesis(text="the parent hypothesis"),
        ["a peer hypothesis"],
        _evolution_context(),
        _EvolutionOperation(),
    )
    assert "Lab Constraints" not in prompt
    assert "{{MISSING" not in prompt


def test_evolution_prompt_includes_research_goal() -> None:
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


def test_evolution_prompt_includes_preferences() -> None:
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
    prompt, _ = _build_evolution_prompt(
        make_hypothesis(text="the parent hypothesis"),
        ["a peer hypothesis"],
        _evolution_context(),
        _EvolutionOperation(),
    )
    assert "Focus on novelty, testability, and potential impact." in prompt


_DISCLOSED_OPERATORS = {
    "enhancement",
    "coherence_feasibility",
    "inspiration",
    "combination",
    "simplification",
    "analogy",
    "out_of_box",
}


def _operator_child_payload(operator: EvolutionOperator) -> dict[str, Any]:
    return {
        "hypothesis": (
            f"The {operator.value} route tests a distinct temporal "
            "checkpoint with an orthogonal perturbation and readout."
        ),
        "explanation": "The operator creates a separately testable path.",
        "experiment": "Perturb the checkpoint and compare the readout.",
        "refinement_summary": f"Applied {operator.value} behavior.",
    }


def _appended_operators() -> list[EvolutionOperator]:
    return [
        operator
        for operator in EvolutionOperator
        if operator_template(operator) == "evolution"
    ]


def _published_operators() -> list[EvolutionOperator]:
    return [
        operator
        for operator in EvolutionOperator
        if operator_template(operator) != "evolution"
    ]


def _operator_prompt(operator: EvolutionOperator) -> str:
    prompt, _ = _build_evolution_prompt(
        hypothesis=make_hypothesis("Parent mechanism."),
        other_hypotheses_texts=["Complementary peer mechanism."],
        context=EvolutionContext(
            model_name="fake/model", meta_review={}, removed_duplicates=[]
        ),
        operation=_EvolutionOperation(
            operator=operator,
            partners=(make_hypothesis("A top-ranked peer approach."),),
        ),
    )
    return prompt


def test_portfolio_contains_every_disclosed_operator() -> None:
    assert {operator.value for operator in EvolutionOperator} == (
        _DISCLOSED_OPERATORS
    )
    appended = _appended_operators()
    assert len({operator_instruction(op) for op in appended}) == len(appended)


def test_every_operator_is_briefed_exactly_once() -> None:
    """A separate template already supplies its own brief; appending another
    duplicates guidance."""
    for operator in _published_operators():
        with pytest.raises(KeyError):
            operator_instruction(operator)
    for operator in _appended_operators():
        assert operator_instruction(operator)


def test_coherence_feasibility_renders_the_published_prompt() -> None:
    assert operator_template(EvolutionOperator.COHERENCE_FEASIBILITY) == (
        "evolution_feasibility"
    )
    enhancement = operator_instruction(EvolutionOperator.ENHANCEMENT)
    assert "feasibility" not in enhancement.lower()
    assert "coherence" not in enhancement.lower()

    prompt = _operator_prompt(EvolutionOperator.COHERENCE_FEASIBILITY)
    assert (
        "You are an expert in scientific research and technological"
        " feasibility analysis." in prompt
    )
    assert (
        "Ensure the revised concept retains its novelty, logical coherence,"
        " and specific articulation." in prompt
    )


def test_selection_covers_every_operator_across_rounds() -> None:
    """Small parent sets must not leave operators structurally unreachable
    across rounds."""
    covered = {
        operator
        for iteration in range(2)
        for operator in select_operators(5, iteration, "coverage-run")
    }
    assert covered == set(EvolutionOperator)


def test_selection_is_deterministic_under_the_seed() -> None:
    first = select_operators(5, 0, "seeded-run")
    again = select_operators(5, 0, "seeded-run")
    assert first == again
    assert len(first) == 5


def test_selection_rotates_across_iterations() -> None:
    round_zero = select_operators(5, 0, "rotating-run")
    round_one = select_operators(5, 1, "rotating-run")
    assert round_zero != round_one


def test_selection_small_pool_and_empty_pool() -> None:
    two = select_operators(2, 0, "express-run")
    assert len(two) == 2
    assert len(set(two)) == 2
    assert select_operators(0, 0, "empty") == []


def test_selection_wraps_when_parents_exceed_operators() -> None:
    nine = select_operators(9, 0, "wrapping-run")
    assert len(nine) == 9
    assert set(nine) == set(EvolutionOperator)


def test_prompt_requires_assigned_operator() -> None:
    prompt, _ = _build_evolution_prompt(
        hypothesis=make_hypothesis("Parent mechanism."),
        other_hypotheses_texts=["Complementary peer mechanism."],
        context=EvolutionContext(
            model_name="fake/model", meta_review={}, removed_duplicates=[]
        ),
        operation=_EvolutionOperation(operator=EvolutionOperator.COMBINATION),
    )
    assert "**Operator:** combination" in prompt
    assert "Combination is required" in prompt


def test_prompt_carries_the_anti_aggregation_guard_for_combination() -> None:
    prompt, _ = _build_evolution_prompt(
        hypothesis=make_hypothesis("Parent mechanism."),
        other_hypotheses_texts=["Complementary peer mechanism."],
        context=EvolutionContext(
            model_name="fake/model", meta_review={}, removed_duplicates=[]
        ),
        operation=_EvolutionOperation(operator=EvolutionOperator.COMBINATION),
    )
    assert (
        "This should not be a mere aggregation of existing methods or"
        " entities. Think out-of-the-box." in prompt
    )


@pytest.mark.parametrize("operator", _appended_operators())
def test_prompt_carries_the_published_reasoning_order(
    operator: EvolutionOperator,
) -> None:
    prompt = _operator_prompt(operator)
    assert "## Reasoning Order" in prompt
    assert "overview of the relevant" in prompt
    assert "synopsis of recent pertinent research" in prompt
    assert "core contribution" in prompt


def test_feasibility_prompt_carries_the_published_guidelines() -> None:
    prompt = _operator_prompt(EvolutionOperator.COHERENCE_FEASIBILITY)
    steps = (
        "Begin with an introductory overview of the relevant scientific"
        " domain.",
        "Provide a concise synopsis of recent pertinent research findings",
        "Articulate a reasoned argument for how current technological"
        " advancements",
        "CORE CONTRIBUTION: Develop a detailed, innovative, and"
        " technologically viable alternative",
    )
    positions = [prompt.index(step) for step in steps]
    assert positions == sorted(positions)


def test_out_of_box_prompt_is_the_published_analogy_prompt() -> None:
    prompt = _operator_prompt(EvolutionOperator.OUT_OF_BOX)

    assert (
        "You are an expert researcher tasked with generating a novel,"
        " singular hypothesis inspired by analogous elements from provided"
        " concepts." in prompt
    )
    assert (
        "Inspiration may be drawn from the following concepts (utilize"
        " analogy and inspiration, not direct replication):" in prompt
    )
    assert "A top-ranked peer approach." in prompt
    assert (
        "This should not be a mere aggregation of existing methods or"
        " entities. Think out-of-the-box." in prompt
    )
    assert "**Operator:** out_of_box" not in prompt
    assert "DO NOT rewrite the hypothesis" not in prompt


async def test_out_of_box_task_draws_partners_from_the_ranked_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_prompt = ""

    async def fake_llm(*, prompt: str, **_: Any) -> dict[str, Any]:
        nonlocal observed_prompt
        observed_prompt = prompt
        return _operator_child_payload(EvolutionOperator.OUT_OF_BOX)

    monkeypatch.setattr(evolve, "call_llm_json", fake_llm)
    parent = make_hypothesis("Parent mechanism.", elo_rating=1500)
    peer = make_hypothesis("Strongest peer approach.", elo_rating=1400)
    state = make_state(hypotheses=[parent, peer])
    context = EvolutionContext(
        model_name="fake/model",
        meta_review={},
        removed_duplicates=[],
        ranked_hypotheses=(parent, peer),
    )

    child, _ = await evolve._build_single_evolution_task(
        state, 0, parent, context, EvolutionOperator.OUT_OF_BOX
    )

    assert child is not None
    assert "## Provided Concepts" in observed_prompt
    assert "Strongest peer approach." in observed_prompt
    assert "No partners are available" not in observed_prompt


@pytest.mark.parametrize("operator", list(EvolutionOperator))
async def test_every_operator_executes_as_a_distinct_evolution_task(
    monkeypatch: pytest.MonkeyPatch,
    operator: EvolutionOperator,
) -> None:
    observed_prompt = ""

    async def fake_llm(*, prompt: str, **_: Any) -> dict[str, Any]:
        nonlocal observed_prompt
        observed_prompt = prompt
        return _operator_child_payload(operator)

    monkeypatch.setattr(evolve, "call_llm_json", fake_llm)
    parent = make_hypothesis(
        "A parent proposal links metabolic state to recovery kinetics."
    )

    child, detail = await evolve_single_hypothesis(
        parent,
        other_hypotheses=[],
        context=EvolutionContext(
            model_name="fake/model",
            meta_review={},
            removed_duplicates=[],
            creation_iteration=2,
        ),
        operation=_EvolutionOperation(operator=operator),
    )

    assert child is not None
    assert detail is not None
    if operator_template(operator) == "evolution":
        assert f"**Operator:** {operator.value}" in observed_prompt
        assert operator_instruction(operator) in observed_prompt
    else:
        assert "## Required Evolution Operator" not in observed_prompt
    assert detail["operator"] == operator.value
    assert child.parent_id == parent.id
    assert child.parent_ids == [parent.id]
    assert child.generation == parent.generation + 1
    assert child.creation_iteration == 2
