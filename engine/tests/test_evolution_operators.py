"""Tests for the disclosed evolution-operator portfolio."""

from typing import Any

import pytest

from co_scientist.agents.evolution import evolve
from co_scientist.agents.evolution.evolution_operators import (
    EvolutionOperator,
    operator_instruction,
    select_operators,
)
from co_scientist.agents.evolution.evolve import evolve_single_hypothesis
from co_scientist.agents.evolution.evolve_prompt import (
    _build_evolution_prompt,
    _EvolutionContext,
    _EvolutionOperation,
)
from tests._state import make_hypothesis

# The six strategies the paper discloses for the Evolution agent, plus the
# analogy operator the engine carries from the expanded operator specs.
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
    """The stubbed LLM response an operator run should turn into a child."""
    return {
        "hypothesis": (
            f"The {operator.value} route tests a distinct temporal "
            "checkpoint with an orthogonal perturbation and readout."
        ),
        "explanation": "The operator creates a separately testable path.",
        "experiment": "Perturb the checkpoint and compare the readout.",
        "refinement_summary": f"Applied {operator.value} behavior.",
    }


def test_portfolio_contains_every_disclosed_operator() -> None:
    """All paper evolution strategies are executable and distinct."""
    assert {operator.value for operator in EvolutionOperator} == (
        _DISCLOSED_OPERATORS
    )
    assert len({operator_instruction(op) for op in EvolutionOperator}) == len(
        EvolutionOperator
    )


def test_coherence_feasibility_is_split_from_enhancement() -> None:
    """Coherence/feasibility is its own operator with its own brief."""
    enhancement = operator_instruction(EvolutionOperator.ENHANCEMENT)
    coherence = operator_instruction(EvolutionOperator.COHERENCE_FEASIBILITY)
    assert "feasibility" not in enhancement.lower()
    assert "coherence" not in enhancement.lower()
    assert "feasibility" in coherence.lower()
    assert "coherence" in coherence.lower()


def test_selection_covers_every_operator_across_rounds() -> None:
    """Consecutive rounds of a tier-sized parent set cover the portfolio.

    The old ``(index + iteration) % len`` round-robin left operators a
    small parent count never reached structurally unselected. Dealing from
    a rotated deck covers all seven operators within two five-parent rounds
    whatever the deck order.
    """
    covered = {
        operator
        for iteration in range(2)
        for operator in select_operators(5, iteration, "coverage-run")
    }
    assert covered == set(EvolutionOperator)


def test_selection_is_deterministic_under_the_seed() -> None:
    """The same (seed, iteration, count) always assigns the same operators."""
    first = select_operators(5, 0, "seeded-run")
    again = select_operators(5, 0, "seeded-run")
    assert first == again
    assert len(first) == 5


def test_selection_rotates_across_iterations() -> None:
    """Later rounds deal different portfolio positions, not the same five."""
    round_zero = select_operators(5, 0, "rotating-run")
    round_one = select_operators(5, 1, "rotating-run")
    assert round_zero != round_one


def test_selection_small_pool_and_empty_pool() -> None:
    """Fewer parents than operators deals distinct operators; zero is safe."""
    two = select_operators(2, 0, "express-run")
    assert len(two) == 2
    assert len(set(two)) == 2
    assert select_operators(0, 0, "empty") == []


def test_selection_wraps_when_parents_exceed_operators() -> None:
    """More parents than operators wraps the deck without dropping any."""
    nine = select_operators(9, 0, "wrapping-run")
    assert len(nine) == 9
    assert set(nine) == set(EvolutionOperator)


def test_prompt_requires_assigned_operator() -> None:
    """Combination tasks explicitly permit synthesis instead of preservation."""
    prompt, _ = _build_evolution_prompt(
        hypothesis=make_hypothesis("Parent mechanism."),
        other_hypotheses_texts=["Complementary peer mechanism."],
        context=_EvolutionContext(
            model_name="fake/model", meta_review={}, removed_duplicates=[]
        ),
        operation=_EvolutionOperation(operator=EvolutionOperator.COMBINATION),
    )
    assert "**Operator:** combination" in prompt
    assert "Combination is required" in prompt


def test_prompt_carries_the_anti_aggregation_guard_for_combination() -> None:
    """Published evolution-07's anti-aggregation guard applies template-wide.

    "This should not be a mere aggregation of existing methods or
    entities. Think out-of-the-box." was absent from every operator in
    evolution.md, including COMBINATION -- the operator it most directly
    polices, since a faithful combination that stops at concatenating its
    partners' methods is exactly what the guard forbids (MP-5).
    """
    prompt, _ = _build_evolution_prompt(
        hypothesis=make_hypothesis("Parent mechanism."),
        other_hypotheses_texts=["Complementary peer mechanism."],
        context=_EvolutionContext(
            model_name="fake/model", meta_review={}, removed_duplicates=[]
        ),
        operation=_EvolutionOperation(operator=EvolutionOperator.COMBINATION),
    )
    assert (
        "This should not be a mere aggregation of existing methods or"
        " entities. Think out-of-the-box." in prompt
    )


@pytest.mark.parametrize("operator", list(EvolutionOperator))
def test_prompt_carries_the_published_reasoning_order(
    operator: EvolutionOperator,
) -> None:
    """Published evolution-06/07's reasoning scaffold applies template-wide.

    Both prompts scaffold the model's reasoning before it writes the
    answer -- a domain overview, a synopsis of recent research, a reasoned
    argument for viability, then the core contribution -- and evolution.md
    dropped it rather than reformatting it into the JSON schema (MP-7).
    Restored template-wide like the MP-5 guard above: the ordering is
    generic scaffolding, not specific to the two operators that happen to
    have a published prompt.
    """
    prompt, _ = _build_evolution_prompt(
        hypothesis=make_hypothesis("Parent mechanism."),
        other_hypotheses_texts=["Complementary peer mechanism."],
        context=_EvolutionContext(
            model_name="fake/model", meta_review={}, removed_duplicates=[]
        ),
        operation=_EvolutionOperation(operator=operator),
    )
    assert "## Reasoning Order" in prompt
    assert "overview of the relevant" in prompt
    assert "synopsis of recent pertinent research" in prompt
    assert "core contribution" in prompt


def test_out_of_box_prompt_permits_core_mechanism_replacement() -> None:
    """Divergent evolution is not contradicted by a preservation directive."""
    prompt, _ = _build_evolution_prompt(
        hypothesis=make_hypothesis("Parent mechanism."),
        other_hypotheses_texts=[],
        context=_EvolutionContext(
            model_name="fake/model", meta_review={}, removed_duplicates=[]
        ),
        operation=_EvolutionOperation(operator=EvolutionOperator.OUT_OF_BOX),
    )

    assert "**Operator:** out_of_box" in prompt
    assert "may replace the parent's mechanism" in prompt
    assert "DO NOT rewrite the hypothesis" not in prompt


@pytest.mark.parametrize("operator", list(EvolutionOperator))
async def test_every_operator_executes_as_a_distinct_evolution_task(
    monkeypatch: pytest.MonkeyPatch,
    operator: EvolutionOperator,
) -> None:
    """Each disclosed operator reaches a child and records its behavior."""
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
        context=_EvolutionContext(
            model_name="fake/model",
            meta_review={},
            removed_duplicates=[],
            creation_iteration=2,
        ),
        operation=_EvolutionOperation(operator=operator),
    )

    assert child is not None
    assert detail is not None
    assert f"**Operator:** {operator.value}" in observed_prompt
    assert operator_instruction(operator) in observed_prompt
    assert detail["operator"] == operator.value
    assert child.parent_id == parent.id
    assert child.parent_ids == [parent.id]
    assert child.generation == parent.generation + 1
    assert child.creation_iteration == 2
