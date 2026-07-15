"""The four generation techniques (SSR §4) and their prompt registry.

Google's Generation agent produces hypotheses four ways. This module names
them as a single enum and maps each to the prompt template that implements it,
so the set is explicit rather than implied by scattered coordinator branches:

- ``LITERATURE_EXPLORATION`` -- search papers and draft hypotheses from
  identified gaps (``generation_draft_with_tools``).
- ``SIMULATED_DEBATE`` -- a simulated multi-expert scientific debate
  (``generation_debate_and_literature`` / ``generation_after_debate``).
- ``ASSUMPTIONS_IDENTIFICATION`` -- decompose the area into assumptions and
  generate hypotheses that challenge the weakest ones
  (``generation_assumptions``).
- ``RESEARCH_EXPANSION`` -- re-enter generation in a later cycle informed by
  the meta-review to explore under-examined regions (not a separate prompt:
  the ``{{meta_review_context}}`` block in the generation prompts carries the
  cross-cycle feedback, and the orchestrator routes back to ``generate`` with
  a higher iteration; see ``generator/graph.py`` and ``nodes/orchestrator``).
"""

from __future__ import annotations

import enum

from co_scientist.models import GenerationMethod


class GenerationTechnique(str, enum.Enum):
    """The four hypothesis-generation techniques (SSR §4)."""

    LITERATURE_EXPLORATION = "literature_exploration"
    SIMULATED_DEBATE = "simulated_debate"
    ASSUMPTIONS_IDENTIFICATION = "assumptions_identification"
    RESEARCH_EXPANSION = "research_expansion"


# Representative prompt-template stem for each technique. RESEARCH_EXPANSION is
# a mode of the debate prompt (re-run in a later cycle with meta-review
# context), so it shares that stem rather than owning a distinct template.
_PROMPT_BY_TECHNIQUE: dict[GenerationTechnique, str] = {
    GenerationTechnique.LITERATURE_EXPLORATION: "generation_draft_with_tools",
    GenerationTechnique.SIMULATED_DEBATE: "generation_debate_and_literature",
    GenerationTechnique.ASSUMPTIONS_IDENTIFICATION: "generation_assumptions",
    GenerationTechnique.RESEARCH_EXPANSION: "generation_after_debate",
}

# The GenerationMethod recorded on a hypothesis produced by each technique.
_METHOD_BY_TECHNIQUE: dict[GenerationTechnique, GenerationMethod] = {
    GenerationTechnique.LITERATURE_EXPLORATION: (
        GenerationMethod.LITERATURE_TOOLS
    ),
    GenerationTechnique.SIMULATED_DEBATE: GenerationMethod.DEBATE,
    GenerationTechnique.ASSUMPTIONS_IDENTIFICATION: (
        GenerationMethod.ASSUMPTIONS
    ),
    GenerationTechnique.RESEARCH_EXPANSION: (
        GenerationMethod.RESEARCH_EXPANSION
    ),
}


def prompt_name_for(technique: GenerationTechnique) -> str:
    """Return the prompt-template stem implementing a generation technique."""
    return _PROMPT_BY_TECHNIQUE[technique]


def method_for(technique: GenerationTechnique) -> GenerationMethod:
    """Return the GenerationMethod recorded for a technique's hypotheses."""
    return _METHOD_BY_TECHNIQUE[technique]
