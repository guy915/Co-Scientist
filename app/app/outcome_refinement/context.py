"""Build the selected parent's bounded evolution context."""

from __future__ import annotations

from typing import Any, cast

from co_scientist.agents.evolution import (
    EvolutionContext,
    prepare_outcome_refinement_context,
)
from co_scientist.models import Hypothesis
from co_scientist.state import WorkflowState


def targeted_context(
    state: dict[str, Any], parent: Hypothesis
) -> EvolutionContext:
    """Keep run guidance while prompting on the selected parent only."""
    return prepare_outcome_refinement_context(
        cast(WorkflowState, state), parent
    )
