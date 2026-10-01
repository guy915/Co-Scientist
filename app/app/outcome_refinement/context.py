"""Build the selected parent's bounded evolution context."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from co_scientist.agents.evolution.evolve import _build_evolution_context
from co_scientist.agents.evolution.evolve_prompt import _EvolutionContext
from co_scientist.models import Hypothesis


def targeted_context(
    state: dict[str, Any], parent: Hypothesis
) -> _EvolutionContext:
    """Keep run guidance while prompting on the selected parent only."""
    scoped_state = {
        **state,
        "hypotheses": [parent],
        "meta_review": {},
        "supervisor_guidance": None,
    }
    context = _build_evolution_context(scoped_state, [], None)
    return replace(
        context,
        state={
            "research_goal": state.get("research_goal"),
            "preferences": state.get("preferences"),
            "lab_constraints": state.get("lab_constraints"),
            "hypotheses": [parent],
        },
        ranked_hypotheses=(parent,),
        meta_review={},
        removed_duplicates=[],
        supervisor_guidance=None,
    )
