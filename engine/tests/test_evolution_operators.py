"""Tests for the disclosed evolution-operator portfolio."""

from co_scientist.models import Hypothesis
from co_scientist.nodes.evolution_operators import (
    EvolutionOperator,
    operator_instruction,
    select_operator,
)
from co_scientist.nodes.evolve_prompt import _build_evolution_prompt


def test_portfolio_contains_every_disclosed_operator() -> None:
    """All material evolution strategies are executable and distinct."""
    assert {operator.value for operator in EvolutionOperator} == {
        "enhancement",
        "simplification",
        "combination",
        "analogy",
        "out_of_box",
    }
    assert len({operator_instruction(op) for op in EvolutionOperator}) == 5


def test_selection_rotates_across_parent_and_iteration() -> None:
    """The task portfolio does not collapse every parent into one rewrite."""
    selected = {select_operator(index, 0) for index in range(5)}
    assert selected == set(EvolutionOperator)
    assert select_operator(0, 1) is EvolutionOperator.SIMPLIFICATION


def test_prompt_requires_assigned_operator() -> None:
    """Combination tasks explicitly permit synthesis instead of preservation."""
    prompt, _ = _build_evolution_prompt(
        hypothesis=Hypothesis(text="Parent mechanism."),
        other_hypotheses_texts=["Complementary peer mechanism."],
        meta_review={},
        removed_duplicates=[],
        supervisor_guidance=None,
        articles_with_reasoning=None,
        tool_registry=None,
        run_setup_guidance=None,
        run_focus_guidance=None,
        operator=EvolutionOperator.COMBINATION,
    )
    assert "**Operator:** combination" in prompt
    assert "Combination is required" in prompt


def test_out_of_box_prompt_permits_core_mechanism_replacement() -> None:
    """Divergent evolution is not contradicted by a preservation directive."""
    prompt, _ = _build_evolution_prompt(
        hypothesis=Hypothesis(text="Parent mechanism."),
        other_hypotheses_texts=[],
        meta_review={},
        removed_duplicates=[],
        supervisor_guidance=None,
        articles_with_reasoning=None,
        tool_registry=None,
        run_setup_guidance=None,
        run_focus_guidance=None,
        operator=EvolutionOperator.OUT_OF_BOX,
    )

    assert "**Operator:** out_of_box" in prompt
    assert "may replace the parent's mechanism" in prompt
    assert "DO NOT rewrite the hypothesis" not in prompt
