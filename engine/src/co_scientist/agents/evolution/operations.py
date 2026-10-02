"""Scientific context operations shared by graph and durable callers."""

from dataclasses import replace
from typing import cast

from co_scientist.agents.evolution.context import (
    EvolutionContext,
    build_evolution_context,
)
from co_scientist.models import Hypothesis
from co_scientist.state import WorkflowState


def prepare_outcome_refinement_context(
    state: WorkflowState, parent: Hypothesis
) -> EvolutionContext:
    """Keep run guidance and evidence while prompting on one selected parent.

    Siblings are supplied separately to the outcome operation for duplicate
    validation. They and unrelated round signals never enter prompt state.

    Args:
        state: The original run state, retained without mutation.
        parent: The only parent the targeted action may refine.

    Returns:
        Parent-only prompt context with the run's shared citation keys.
    """
    scoped_state = cast(
        WorkflowState,
        {
            **state,
            "hypotheses": [parent],
            "meta_review": {},
            "supervisor_guidance": None,
        },
    )
    context = build_evolution_context(scoped_state, [], None)
    return replace(
        context,
        state=cast(
            WorkflowState,
            {
                "research_goal": state.get("research_goal"),
                "preferences": state.get("preferences"),
                "lab_constraints": state.get("lab_constraints"),
                "hypotheses": [parent],
            },
        ),
        ranked_hypotheses=(parent,),
        meta_review={},
        removed_duplicates=[],
        supervisor_guidance=None,
    )
