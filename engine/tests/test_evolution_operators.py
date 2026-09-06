"""Tests for the disclosed evolution-operator portfolio."""

from typing import Any

import pytest

from co_scientist.agents.evolution import evolve
from co_scientist.agents.evolution.evolution_operators import (
    EvolutionOperator,
    operator_instruction,
    operator_template,
    select_operators,
)
from co_scientist.agents.evolution.evolve import evolve_single_hypothesis
from co_scientist.agents.evolution.evolve_prompt import (
    _build_evolution_prompt,
    _EvolutionContext,
    _EvolutionOperation,
)
from tests._state import make_hypothesis, make_state

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


def _appended_operators() -> list[EvolutionOperator]:
    """The operators briefed by an instruction appended to evolution.md."""
    return [
        operator
        for operator in EvolutionOperator
        if operator_template(operator) == "evolution"
    ]


def _published_operators() -> list[EvolutionOperator]:
    """The operators that render a published prompt of their own."""
    return [
        operator
        for operator in EvolutionOperator
        if operator_template(operator) != "evolution"
    ]


def _operator_prompt(operator: EvolutionOperator) -> str:
    """Render one operator's evolution prompt with a partner available."""
    prompt, _ = _build_evolution_prompt(
        hypothesis=make_hypothesis("Parent mechanism."),
        other_hypotheses_texts=["Complementary peer mechanism."],
        context=_EvolutionContext(
            model_name="fake/model", meta_review={}, removed_duplicates=[]
        ),
        operation=_EvolutionOperation(
            operator=operator,
            partners=(make_hypothesis("A top-ranked peer approach."),),
        ),
    )
    return prompt


def test_portfolio_contains_every_disclosed_operator() -> None:
    """All paper evolution strategies are executable and distinct."""
    assert {operator.value for operator in EvolutionOperator} == (
        _DISCLOSED_OPERATORS
    )
    appended = _appended_operators()
    assert len({operator_instruction(op) for op in appended}) == len(appended)


def test_every_operator_is_briefed_exactly_once() -> None:
    """An operator carries a published template or an instruction, not both.

    The two operators Google published a whole prompt for state their own
    brief in the prompt's role sentence; a second, paraphrased instruction
    appended beside it is the drift this split exists to remove.
    """
    for operator in _published_operators():
        with pytest.raises(KeyError):
            operator_instruction(operator)
    for operator in _appended_operators():
        assert operator_instruction(operator)


def test_coherence_feasibility_renders_the_published_prompt() -> None:
    """Coherence/feasibility is its own operator with its own brief.

    Its brief is published A.6 itself (feasibility improvement), which is
    why it renders a template rather than an appended instruction; the
    enhancement operator it was split out of stays on evolution.md.
    """
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


@pytest.mark.parametrize("operator", _appended_operators())
def test_prompt_carries_the_published_reasoning_order(
    operator: EvolutionOperator,
) -> None:
    """Published evolution-06/07's reasoning scaffold applies template-wide.

    Both prompts scaffold the model's reasoning before it writes the
    answer -- a domain overview, a synopsis of recent research, a reasoned
    argument for viability, then the core contribution -- and evolution.md
    dropped it rather than reformatting it into the JSON schema (MP-7).
    Restored for every operator evolution.md still serves; the two with a
    published prompt of their own carry the published imperatives instead
    (see below), which is the same scaffold in Google's own words.
    """
    prompt = _operator_prompt(operator)
    assert "## Reasoning Order" in prompt
    assert "overview of the relevant" in prompt
    assert "synopsis of recent pertinent research" in prompt
    assert "core contribution" in prompt


def test_feasibility_prompt_carries_the_published_guidelines() -> None:
    """A.6's four-step scaffold is present verbatim, in published order."""
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
    """A.7's role, its concepts input, and its anti-aggregation guard.

    MP-8: the operator carrying A.7's name now also carries its content --
    one hypothesis reasoned by analogy from the supplied concepts -- so the
    partner block it never used to receive is the published {hypotheses}
    input, and no paraphrased operator instruction is appended beside it.
    """
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
    """A.7's {hypotheses} input is filled on the node's own task path.

    ``_build_single_evolution_task`` is where an operator is granted (or
    denied) partners, so MP-8's resolution is pinned here rather than only
    at ``_build_evolution_prompt``: without OUT_OF_BOX in
    ``_PARTNER_OPERATORS`` the published concepts block renders its
    empty-pool note on every real run.
    """
    observed_prompt = ""

    async def fake_llm(*, prompt: str, **_: Any) -> dict[str, Any]:
        nonlocal observed_prompt
        observed_prompt = prompt
        return _operator_child_payload(EvolutionOperator.OUT_OF_BOX)

    monkeypatch.setattr(evolve, "call_llm_json", fake_llm)
    parent = make_hypothesis("Parent mechanism.", elo_rating=1500)
    peer = make_hypothesis("Strongest peer approach.", elo_rating=1400)
    state = make_state(hypotheses=[parent, peer])
    context = _EvolutionContext(
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
    if operator_template(operator) == "evolution":
        assert f"**Operator:** {operator.value}" in observed_prompt
        assert operator_instruction(operator) in observed_prompt
    else:
        # A published template states the brief in its own role sentence;
        # the operator itself is recorded on the child, not in the prompt.
        assert "## Required Evolution Operator" not in observed_prompt
    assert detail["operator"] == operator.value
    assert child.parent_id == parent.id
    assert child.parent_ids == [parent.id]
    assert child.generation == parent.generation + 1
    assert child.creation_iteration == 2
