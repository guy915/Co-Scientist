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
from tests._llm_fake import stub_call_llm_json
from tests._state import make_hypothesis, make_state


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


def test_diversity_instruction_long_text_truncated_with_marker() -> None:
    long_text = "x" * 250
    result = _format_diversity_instruction([long_text], [])
    assert ("x" * 200 + "...") in result
    assert long_text not in result


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


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        (
            {"refinement_priorities": ["clarity", "safety"]},
            "Refinement Priorities:** clarity, safety",
        ),
        (
            {"refinement_priorities": "narrow the mechanism"},
            "Refinement Priorities:** narrow the mechanism",
        ),
        (
            {"iteration_strategy": "converge on the top mechanism"},
            "Iteration Strategy:** converge on the top mechanism",
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
    assert "## Supervisor Guidance for Evolution" in result
    assert expected in result
    assert result.index("## Supervisor Guidance") < result.index(expected)


def _evolution_context(**state_overrides: Any) -> EvolutionContext:
    return EvolutionContext(
        model_name="test-model",
        meta_review={},
        removed_duplicates=[],
        state=make_state(**state_overrides),
    )


def test_evolution_prompt_renders_lab_constraints() -> None:
    prompt, _ = _build_evolution_prompt(
        make_hypothesis(text="the parent hypothesis"),
        ["a peer hypothesis"],
        _evolution_context(lab_constraints=["No mammalian cell culture"]),
        _EvolutionOperation(),
    )
    assert "## Scientist's Lab Constraints" in prompt
    assert "No mammalian cell culture" in prompt


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


def test_selection_covers_every_operator_across_rounds() -> None:
    """Small parent sets must not leave operators structurally unreachable
    across rounds."""
    covered = {
        operator
        for iteration in range(2)
        for operator in select_operators(5, iteration, "coverage-run")
    }
    assert covered == set(EvolutionOperator)


def test_selection_is_seeded_and_rotates_across_iterations() -> None:
    round_zero = select_operators(5, 0, "rotating-run")
    assert round_zero == select_operators(5, 0, "rotating-run")
    assert round_zero != select_operators(5, 1, "rotating-run")


async def test_out_of_box_task_draws_partners_from_the_ranked_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = stub_call_llm_json(
        monkeypatch,
        evolve,
        _operator_child_payload(EvolutionOperator.OUT_OF_BOX),
        copy_response=True,
    )
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

    observed_prompt = calls[-1]["prompt"]
    assert child is not None
    assert "## Provided Concepts" in observed_prompt
    assert "Strongest peer approach." in observed_prompt
    assert "No partners are available" not in observed_prompt


@pytest.mark.parametrize("operator", list(EvolutionOperator))
async def test_every_operator_executes_as_a_distinct_evolution_task(
    monkeypatch: pytest.MonkeyPatch,
    operator: EvolutionOperator,
) -> None:
    calls = stub_call_llm_json(
        monkeypatch,
        evolve,
        _operator_child_payload(operator),
        copy_response=True,
    )
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

    observed_prompt = calls[-1]["prompt"]
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
