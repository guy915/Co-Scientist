import dataclasses
from dataclasses import replace
from typing import Any, cast

from co_scientist.agents.generation.citations import (
    ReferenceIndex,
    build_reference_index,
)
from co_scientist.models import Hypothesis, rank_by_elo
from co_scientist.state import WorkflowState


@dataclasses.dataclass(frozen=True)
class EvolutionContext:
    """Prompt keys and child citations use one reference index; round-ranked
    context stays stable while processing parents."""

    model_name: str
    meta_review: dict[str, Any]
    removed_duplicates: list[str]
    creation_iteration: int | None = None
    supervisor_guidance: dict[str, Any] | None = None
    articles_with_reasoning: str | None = None
    run_id: str | None = None
    tool_registry: Any | None = None
    run_setup_guidance: str | None = None
    run_focus_guidance: str | None = None
    proximity_graph: dict[str, Any] | None = None
    ranked_hypotheses: tuple[Hypothesis, ...] = ()
    state: WorkflowState | None = None
    reference_index: ReferenceIndex | None = None


def build_evolution_context(
    state: WorkflowState,
    removed_duplicates: list[str],
    supervisor_guidance: dict[str, Any] | None,
) -> EvolutionContext:
    return EvolutionContext(
        model_name=state["model_name"],
        meta_review=state.get("meta_review", {}),
        removed_duplicates=removed_duplicates,
        creation_iteration=state.get("current_iteration", 0),
        supervisor_guidance=supervisor_guidance,
        articles_with_reasoning=state.get("articles_with_reasoning"),
        run_id=state.get("run_id"),
        tool_registry=state.get("tool_registry"),
        run_setup_guidance=state.get("run_setup_guidance"),
        run_focus_guidance=state.get("run_focus_guidance"),
        proximity_graph=state.get("proximity_graph"),
        ranked_hypotheses=tuple(rank_by_elo(state["hypotheses"])),
        state=state,
        # Build one C* index per round so prompt keys and all child resolutions
        # agree.
        reference_index=build_reference_index(
            state.get("articles"), state.get("context_enrichment_sources")
        ),
    )


def prepare_outcome_refinement_context(
    state: WorkflowState, parent: Hypothesis
) -> EvolutionContext:
    """Siblings belong only to duplicate validation; unrelated round signals
    must not enter the selected-parent outcome prompt."""
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
