"""State-derived prompt sections for the Evolve node.

Split out of ``evolve_prompt`` to keep that module within the size cap.
These four helpers share one shape: read a single field off the run's
``WorkflowState`` (through ``_EvolutionContext.state``) into the matching
"evolution" prompt-template variable, rendering an empty section when the
context carries no state (as some tests construct). Lab constraints (K5)
and falsified assumptions (K9) predate this split; research goal (MP-2)
and preferences (MP-3) are the additions that pushed ``evolve_prompt``
over the line-count ceiling. ``evolve_prompt`` re-exports every name here
so its namespace keeps resolving for callers and monkeypatches alike.
"""

from typing import TYPE_CHECKING

from co_scientist.agents.generation.assumption_feedback import (
    build_falsified_assumptions_section,
)
from co_scientist.prompts import format_lab_constraints_section

if TYPE_CHECKING:
    from co_scientist.agents.evolution.evolve_prompt import _EvolutionContext


def _lab_constraints_section(context: "_EvolutionContext") -> str:
    """Renders the scientist's lab constraints for this refinement (K5).

    Feasibility improvements must respect what the scientist's lab can
    actually do. The block renders its own header and is empty when the
    run carries no lab constraints, which keeps the prompt byte-identical
    to its pre-K5 shape.
    """
    if context.state is None:
        return ""
    return format_lab_constraints_section(context.state.get("lab_constraints"))


def _research_goal_text(context: "_EvolutionContext") -> str:
    """Renders the run's research goal for this refinement (MP-2).

    Every published Evolution prompt opens with the goal (evolution-06,
    evolution-07); _EvolutionContext has no dedicated field for it, so
    this reads it from context.state, mirroring
    _lab_constraints_section/_falsified_assumptions_section below. Blank
    only in a context built without state, as some tests do.
    """
    if context.state is None:
        return ""
    return context.state.get("research_goal") or ""


def _preferences_text(context: "_EvolutionContext") -> str | None:
    """Reads the scientist's stated preferences for this refinement (MP-3).

    Published evolution-06/evolution-07 both surface {preferences} as the
    hypothesis's evaluation criteria; format_preferences (the same helper
    the Generation agent's prompts already use for this field) supplies
    the default when the scientist set none. _EvolutionContext has no
    dedicated field for it, so this reads context.state like
    _research_goal_text above.
    """
    if context.state is None:
        return None
    return context.state.get("preferences")


def _falsified_assumptions_section(context: "_EvolutionContext") -> str:
    """Renders the run's verified-wrong assumptions for this refinement.

    Feeds audit K9's evolution half: the assumptions deep verification
    already falsified here, so a refinement does not rebuild on the same
    broken ground. The block renders its own header and is empty until a
    hypothesis has been weakened. The specific parent's own probes already
    reach the prompt through the specialist-feedback ledger, so this adds
    only the run-wide record.
    """
    if context.state is None:
        return ""
    return build_falsified_assumptions_section(context.state.get("hypotheses"))
