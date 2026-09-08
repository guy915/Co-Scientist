"""JSON schema for the hypothesis-evolution stage.

Shapes the output of the three evolution prompt templates (``evolution``,
``evolution_feasibility``, ``evolution_out_of_box``), consumed by the
refinement step in ``agents/evolution/evolve.py``. Split out of
``synthesis.py`` at that module's size cap; ``synthesis`` re-exports the
name, so existing importers are unchanged.
"""

from typing import Any

from co_scientist.schemas.builders import obj

# Evolution's experiment and title fields ask for exactly what generation's
# do, so they are the same objects rather than second copies of the wording
# (schema dicts are never mutated; sharing them by identity is this
# package's established pattern). _TITLE_FIELD's ask -- a compact authored
# noun phrase -- reads identically whether the hypothesis is new or refined
# (R14-12), so it needs no evolution-specific rewording the way explanation
# does below. The sibling explanation field legitimately differs -- it asks
# for the refinements -- so it is written out below.
#
# The four proposal sections below are shared the same way, and for a
# sharper reason: they used to be inherited from the parent because the
# evolution LLM was never asked for them. Production extended run bc77950f
# (2026-09-08) evolved seven children and every one published its parent's
# mechanism and safety text byte-identically -- including a verteporfin
# child carrying a palbociclib mechanism paragraph, whose categorical
# claims therefore named a molecule it does not propose and which no
# retrieval could ever support. A child's sections must describe the
# child, so the refinement is asked for them in the call it already makes.
from co_scientist.schemas.generation import (
    _EXPERIMENT_FIELD,
    _INTRODUCTION_FIELD,
    _LITERATURE_GROUNDING_FIELD,
    _RECENT_FINDINGS_FIELD,
    _SAFETY_TOXICITY_FIELD,
    _TITLE_FIELD,
)

# Evolution schema
# Shapes the "evolution" prompt output, consumed by the
# hypothesis-refinement step in agents/evolution/evolve.py. Represents a
# single refined hypothesis (evolution runs one hypothesis at a time);
# refinement_summary
# is a human-readable diff-style note, not used for further LLM prompting.
#
# Multi-parent combination identifies the partners it merged by the
# positional index the prompt assigned them -- never by echoing their text,
# which would scale the response with the partners' length (the same trap
# proximity clustering hit; see proximity_dedup._match_cluster_member).
EVOLUTION_SCHEMA: dict[str, Any] = {
    "name": "hypothesis_evolution",
    "strict": False,
    "schema": obj(
        {
            "title": _TITLE_FIELD,
            "introduction": _INTRODUCTION_FIELD,
            "recent_findings": _RECENT_FINDINGS_FIELD,
            "literature_grounding": _LITERATURE_GROUNDING_FIELD,
            "safety_and_toxicity": _SAFETY_TOXICITY_FIELD,
            "hypothesis": {
                "type": "string",
                "description": (
                    "Refined mechanistic hypothesis in the domain's"
                    " natural language, naming entities, mechanism, and"
                    " the testable prediction (no fixed phrasing)."
                ),
            },
            "refinement_summary": {
                "type": "string",
                "description": (
                    "Summary of changes and improvements made during evolution."
                ),
            },
            "explanation": {
                "type": "string",
                "description": (
                    "Updated step-by-step layman explanation reflecting"
                    " any refinements made (4-6 sentences)"
                ),
            },
            "experiment": _EXPERIMENT_FIELD,
            "combined_partners": {
                "type": "array",
                "items": {"type": "integer"},
                "description": (
                    "Combination operator only: the 1-based positional "
                    "indices of the partner hypotheses whose mechanisms "
                    "this refinement merges. Omit for every other operator "
                    "and never repeat a partner's text."
                ),
            },
        },
        # Identification only, and only for the combination operator; every
        # other operator omits it.
        optional=("combined_partners",),
    ),
}
