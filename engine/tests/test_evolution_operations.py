"""Public evolution context preserves round evidence and targeted isolation."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict

import pytest

from co_scientist.agents.evolution import (
    EvolutionContext,
    build_evolution_context,
    prepare_outcome_refinement_context,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _build_evolution_prompt,
    _EvolutionOperation,
)
from co_scientist.state import WorkflowState
from tests._state import make_article, make_hypothesis, make_state


def _state() -> WorkflowState:
    """Include unrelated signals alongside retained guidance and sources."""
    return make_state(
        hypotheses=[
            make_hypothesis(text="Selected parent mechanism", elo_rating=900),
            make_hypothesis(
                text="Unrelated sibling mechanism", elo_rating=1500
            ),
        ],
        research_goal="Measure the parent mechanism",
        preferences="Use falsifiable interventions",
        lab_constraints=["Only cell culture"],
        current_iteration=4,
        meta_review={"common_weaknesses": ["Unrelated meta-review signal"]},
        supervisor_guidance={
            "workflow_plan": {
                "evolution_phase": {
                    "iteration_strategy": "Unrelated supervisor signal"
                }
            }
        },
        removed_duplicates=[{"text": "Unrelated removed duplicate"}],
        run_setup_guidance="Use the supplied setup",
        run_focus_guidance="Test a narrow causal question",
        articles_with_reasoning="Analyzed literature evidence",
        articles=[
            make_article(
                title="Retained paper", used_in_analysis=True, year=2025
            ),
            make_article(title="Unread paper", used_in_analysis=False),
        ],
        context_enrichment_sources=[
            {"display": "Retained knowledge source", "tool_id": "source-tool"}
        ],
        proximity_graph={"edges": []},
    )


def test_public_context_is_frozen_and_preserves_all_defaults() -> None:
    context = EvolutionContext(
        model_name="test-model", meta_review={}, removed_duplicates=[]
    )
    assert asdict(context) == {
        "model_name": "test-model",
        "meta_review": {},
        "removed_duplicates": [],
        "creation_iteration": None,
        "supervisor_guidance": None,
        "articles_with_reasoning": None,
        "run_id": None,
        "tool_registry": None,
        "run_setup_guidance": None,
        "run_focus_guidance": None,
        "proximity_graph": None,
        "ranked_hypotheses": (),
        "state": None,
        "reference_index": None,
    }
    with pytest.raises(FrozenInstanceError):
        context.model_name = "changed"  # type: ignore[misc]


def _assert_retained_evidence(
    context: EvolutionContext, state: WorkflowState
) -> None:
    assert context.model_name == state["model_name"]
    assert context.creation_iteration == 4
    assert context.run_id == state["run_id"]
    assert context.tool_registry is state["tool_registry"]
    assert context.proximity_graph is state["proximity_graph"]
    assert context.run_setup_guidance == state["run_setup_guidance"]
    assert context.run_focus_guidance == state["run_focus_guidance"]
    assert context.articles_with_reasoning == state["articles_with_reasoning"]
    assert context.reference_index is not None
    assert list(context.reference_index.sources) == ["C1", "C2"]
    assert context.reference_index.sources["C1"]["title"] == "Retained paper"
    assert context.reference_index.sources["C2"]["tool_id"] == "source-tool"


def test_round_context_ranks_full_pool_and_retains_reference_keys() -> None:
    state = _state()
    parent, sibling = state["hypotheses"]
    duplicates = ["Unrelated removed duplicate"]
    guidance = state["supervisor_guidance"]
    context = build_evolution_context(state, duplicates, guidance)

    assert context.state is state
    assert context.ranked_hypotheses == (sibling, parent)
    assert context.meta_review is state["meta_review"]
    assert context.removed_duplicates is duplicates
    assert context.supervisor_guidance is guidance
    _assert_retained_evidence(context, state)


def test_outcome_context_limits_prompt_to_parent_and_retains_evidence() -> None:
    state = _state()
    original = deepcopy(state)
    parent, sibling = state["hypotheses"]
    context = prepare_outcome_refinement_context(state, parent)

    assert context.state is not None
    assert dict(context.state) == {
        "research_goal": state["research_goal"],
        "preferences": state["preferences"],
        "lab_constraints": state["lab_constraints"],
        "hypotheses": [parent],
    }
    assert context.ranked_hypotheses == (parent,)
    assert context.meta_review == {}
    assert context.removed_duplicates == []
    assert context.supervisor_guidance is None
    _assert_retained_evidence(context, state)
    prompt, _ = _build_evolution_prompt(
        parent, [], context, _EvolutionOperation()
    )
    for text in (
        parent.text,
        state["research_goal"],
        "Use falsifiable interventions",
        "Only cell culture",
        "Use the supplied setup",
        "Test a narrow causal question",
        "Analyzed literature evidence",
        "[C1]",
        "[C2]",
    ):
        assert text in prompt
    for text in (
        sibling.text,
        "Unrelated meta-review signal",
        "Unrelated supervisor signal",
        "Unrelated removed duplicate",
        "Unread paper",
    ):
        assert text not in prompt
    assert state == original
    assert state["hypotheses"] == [parent, sibling]
