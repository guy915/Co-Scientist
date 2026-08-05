"""Prompt builders for the debate-based hypothesis generation flow."""

from dataclasses import dataclass, field
from typing import Any

from co_scientist.constants import DEBATE_MAX_TURNS
from co_scientist.prompts._common import (
    PromptRunContext,
    _csv_value,
    _format_meta_review_context,
    _run_guidance_section,
)
from co_scientist.prompts.generation_formatting import (
    _build_citation_reference_section,
    format_articles_metadata,
    format_user_hypotheses,
)
from co_scientist.prompts.loading import (
    _get_domain_variables,
    load_prompt,
    load_prompt_with_schema,
)


def _format_debate_key_areas_section(
    key_areas: list[Any], *, needs_header: bool
) -> list[str]:
    """Format the key-research-areas slice of debate supervisor guidance.

    Args:
        key_areas: Key research areas from the supervisor's goal analysis.
        needs_header: Whether to emit the "Key research areas" header, i.e.
            no earlier section already introduced the guidance block.

    Returns:
        Section lines, or an empty list when key_areas is empty.
    """
    if not key_areas:
        return []

    sections = []
    if needs_header:
        sections.append("Key research areas to consider:\n")
    for area in key_areas:
        sections.append(f"- {area}\n")
    return sections


def _format_debate_generation_phase_section(
    generation_phase: dict[str, Any], *, needs_header: bool
) -> list[str]:
    """Format the generation-phase slice of debate supervisor guidance.

    Args:
        generation_phase: The `workflow_plan.generation_phase` dict from
            supervisor guidance.
        needs_header: Whether to emit the "Generation guidance" header, i.e.
            no earlier section already introduced the guidance block.

    Returns:
        Section lines, or an empty list when generation_phase is empty.
    """
    if not generation_phase:
        return []

    sections = []
    if needs_header:
        sections.append("Generation guidance:\n")
    if generation_phase.get("focus_areas"):
        focus = _csv_value(generation_phase["focus_areas"])
        sections.append(f"Focus on: {focus}\n")
    return sections


def _format_supervisor_guidance_for_debate(
    supervisor_guidance: dict[str, Any] | None,
) -> str:
    """Format supervisor guidance for the debate generation prompt.

    Args:
        supervisor_guidance: Supervisor guidance dict from workflow state.

    Returns:
        A guidance section combining key research areas and generation-phase
        focus areas, or an empty string when neither is present.
    """
    if not supervisor_guidance or not isinstance(supervisor_guidance, dict):
        return ""

    goal_analysis = supervisor_guidance.get("research_goal_analysis", {})
    workflow_plan = supervisor_guidance.get("workflow_plan", {})
    generation_phase = workflow_plan.get("generation_phase", {})

    sections = _format_debate_key_areas_section(
        goal_analysis.get("key_areas", []), needs_header=True
    )
    sections.extend(
        _format_debate_generation_phase_section(
            generation_phase, needs_header=not sections
        )
    )

    return "".join(sections)


_DEBATE_FINAL_TURN_INSTRUCTIONS = """

## FINAL TURN - OUTPUT FORMAT

This is the final turn of the debate. Based on the discussion above, output \
your finalized hypothesis in JSON format with all four required components. \
Write as a domain expert in the field of the research goal; do not force an \
engineering or product framing, and do not impose an artificial length limit.

### 1. hypothesis (required)
State the proposed mechanistic claim or relationship and the specific, \
testable prediction it makes. Use the natural language of the goal's \
scientific domain (molecular, cellular, physical, chemical, ecological, \
etc.). Name the entities, mechanism, direction of effect, and conditions \
precisely. Distinguish what is grounded in evidence from what is proposed. \
Do NOT begin with a fixed phrase such as "We want to develop"; write the \
claim directly. Be as long as the science requires — do not compress a \
mechanism into two sentences.

Example: "Partial inhibition of enzyme E in tissue T reduces the flux of \
metabolite M through pathway P, which in turn upregulates receptor R via the \
loss of feedback repression; the testable prediction is that E inhibition \
raises surface R density and downstream signaling in a dose-dependent manner, \
reversible by exogenous M."

### 2. explanation (required)
Mechanistic rationale for a scientific audience:
- The core problem or gap being addressed
- Why the proposed mechanism is plausible and how its components interact
- The boundary between established evidence and inference in this proposal

### 3. literature_grounding (required)
Explicit grounding with inline citation keys (2-4 sentences).
- If a Citation Reference List was provided above, use ONLY those `[C*]` keys \
(e.g. `[C1]`, `[C2]`, `[C3]`)
- Do NOT invent author-year citations — only use keys from the list
- If no Citation Reference List was provided, state: "This hypothesis is \
formulated without access to a literature review."

Example: "This mechanism builds on the reported activity of enzyme E [C1] and \
the feedback regulation of receptor R by metabolite M [C2]. It extends those \
findings to tissue T, where the interaction has not been directly measured \
[C3]."

### 4. experiment (required)
Concrete experimental design with the models/systems, methodology, controls, \
readouts/metrics, and an explicit falsification criterion.

Example format: "Objective: Test whether E inhibition raises surface R density \
in tissue T. Systems: primary T cells and an aged mouse model. Methodology: \
(1) apply a selective E inhibitor across a dose range, (2) quantify surface R \
by flow cytometry and downstream signaling by phospho-immunoblot, (3) rescue \
with exogenous M. Controls: vehicle, an inactive analog, and an R-knockdown \
arm. Falsification: the hypothesis fails if E inhibition does not change R \
density or if the effect is not reversed by exogenous M."

---

Output exactly 1 hypothesis as valid JSON:
{
  "hypotheses": [
    {
      "hypothesis": "...",
      "explanation": "...",
      "literature_grounding": "...",
      "experiment": "..."
    }
  ]
}

IMPORTANT: Use plain text with standard punctuation (no LaTeX, no decorative \
Unicode).
"""

# Default task instruction for the literature-aware debate template's
# {{instructions}} slot, mirroring the draft-with-tools builder's fallback
# (DraftPromptRequest.instructions). WorkflowState carries no run-level
# instructions key, so the slot is filled from the request when a caller
# supplies one and from this default otherwise -- it must never render as
# a {{MISSING:...}} sentinel.
_DEFAULT_DEBATE_INSTRUCTIONS = (
    "Focus on creative ideation - debate diverse hypotheses, building on"
    " the user-provided starting hypotheses above when present."
)


def _format_debate_attributes(attributes: str | list[str] | None) -> str:
    """Format debate-prompt attributes as a comma-joined string.

    Shared by _build_debate_prompt_variables to keep the ternary out of the
    variables dict literal.
    """
    if isinstance(attributes, list):
        return ", ".join(attributes) or "testable and falsifiable"
    return attributes or "testable and falsifiable"


def _build_debate_literature_variables(
    articles_with_reasoning: str | None,
    articles: list[Any] | None,
    reference_list: str,
) -> dict[str, Any]:
    """Build the literature-context template variables for debate prompts.

    articles_with_reasoning is included only when provided, so the template
    can distinguish "no literature review ran" from "ran but empty".
    """
    variables: dict[str, Any] = {
        "articles_metadata": format_articles_metadata(articles or []),
        "citation_reference_section": _build_citation_reference_section(
            reference_list or ""
        ),
    }
    if articles_with_reasoning:
        variables["articles_with_reasoning"] = articles_with_reasoning
    return variables


@dataclass(frozen=True)
class DebatePromptRequest:
    """Inputs for one turn of the debate-based generation prompt.

    Attributes:
        research_goal: The run's research goal.
        hypotheses_count: How many hypotheses the debate must produce.
        transcript: The debate transcript accumulated so far.
        preferences: Free-text user preferences, if any.
        attributes: Desired hypothesis attributes, as text or a list.
        user_hypotheses: Seed hypotheses supplied by the user.
        instructions: Custom task instructions for the debate, if any.
        is_final_turn: Whether this is the schema-constrained final turn.
        articles_with_reasoning: The literature-review synthesis text; its
            presence also selects the literature-aware template.
        articles: Literature-review articles for citation metadata.
        reference_list: The ``[C*]`` citation reference list.
        context: Run-scoped prompt context (supervisor guidance,
            meta-review, tool registry, run setup/focus guidance).
    """

    research_goal: str
    hypotheses_count: int
    transcript: str
    preferences: str | None = None
    attributes: str | list[str] | None = None
    user_hypotheses: list[str] | None = None
    instructions: str | None = None
    is_final_turn: bool = False
    articles_with_reasoning: str | None = None
    articles: list[Any] | None = None
    reference_list: str = ""
    context: PromptRunContext = field(default_factory=PromptRunContext)


def _discussion_turn_budget() -> int:
    """Return how many conversational turns a debate gets before synthesis.

    Derived from ``DEBATE_MAX_TURNS`` rather than written into the template,
    because the panel paces itself against whatever number it is told. The
    templates used to state "typically 3-5 conversational turns" as prose
    while the loop ran a fixed five, and the two then drifted independently
    -- a stale figure here reads as a real instruction to the model, so it
    has to be single-sourced from the constant the loop actually enforces.

    The last turn is the schema-constrained synthesis, so the discussion
    budget is one short of the ceiling.
    """
    return max(1, DEBATE_MAX_TURNS - 1)


def _build_debate_base_variables(req: DebatePromptRequest) -> dict[str, Any]:
    """Build the goal/transcript/user-input core of the debate variables.

    The literature-aware template declares a {{user_hypotheses}} and an
    {{instructions}} slot, so both are always produced: user hypotheses
    render as an explicit "none provided" line when absent, and
    instructions fall back to the default task instruction -- neither may
    render as a {{MISSING:...}} sentinel.
    """
    return {
        "goal": req.research_goal,
        "hypotheses_count": req.hypotheses_count,
        "discussion_turns": _discussion_turn_budget(),
        "transcript": req.transcript or "",
        "preferences": req.preferences
        or "Novel, testable, scientifically sound, specific, and diverse"
        " hypotheses",
        "attributes": _format_debate_attributes(req.attributes),
        "user_hypotheses": format_user_hypotheses(req.user_hypotheses),
        "instructions": req.instructions or _DEFAULT_DEBATE_INSTRUCTIONS,
    }


def _build_debate_guidance_variables(
    context: PromptRunContext,
) -> dict[str, Any]:
    """Build the guidance/context/domain variables for the debate prompt.

    Covers supervisor guidance, cross-iteration meta-review context (blank
    on iteration 1), run setup/focus guidance, and the domain-specific
    prompt customizations from the tool registry.

    Args:
        context: Run-scoped prompt context for this debate turn.

    Returns:
        Dict of the guidance, meta-review, and domain template variables.
    """
    variables: dict[str, Any] = {
        "supervisor_guidance": _format_supervisor_guidance_for_debate(
            context.supervisor_guidance
        ),
        "meta_review_context": _format_meta_review_context(context.meta_review),
        "run_guidance": _run_guidance_section(context),
    }
    variables.update(_get_domain_variables(context.tool_registry))
    return variables


def _build_debate_prompt_variables(
    req: DebatePromptRequest,
) -> dict[str, Any]:
    """Build the dict of template variables for the debate generation prompt.

    Args:
        req: The resolved debate-prompt request for this turn.

    Returns:
        Dict of template variables for the debate prompt.
    """
    variables = _build_debate_base_variables(req)
    variables.update(
        _build_debate_literature_variables(
            req.articles_with_reasoning, req.articles, req.reference_list
        )
    )
    variables.update(_build_debate_guidance_variables(req.context))
    return variables


def _render_debate_prompt(
    variables: dict[str, Any],
    articles_with_reasoning: str | None,
    is_final_turn: bool,
) -> tuple[str, dict[str, Any] | None]:
    """Render the debate prompt for one turn, given its resolved variables.

    The template follows literature availability
    (generation_debate_and_literature when a lit review synthesis exists,
    generation_after_debate otherwise). Non-final turns are conversational
    and schema-less. The final turn is schema-constrained, with the JSON
    output instructions concatenated verbatim after the rendered template.

    Returns:
        Tuple of (formatted prompt string, JSON schema dict or None).
    """
    prompt_name = (
        "generation_debate_and_literature"
        if articles_with_reasoning
        else "generation_after_debate"
    )
    if not is_final_turn:
        return load_prompt(prompt_name, variables), None

    prompt, schema = load_prompt_with_schema(prompt_name, variables)
    # Concatenated verbatim after the rendered template (never run through
    # substitute_variables), so the literal braces in the JSON example below
    # need no {{}} escaping.
    prompt = prompt + _DEBATE_FINAL_TURN_INSTRUCTIONS
    return prompt, schema


# Called by agents/generation/debate.py once per debate turn. Template
# choice depends on literature availability
# (generation_debate_and_literature vs generation_after_debate), and the
# final turn switches from free-form discussion to schema-constrained JSON
# output (GENERATION_SCHEMA).
def get_debate_generation_prompt(
    req: DebatePromptRequest,
) -> tuple[str, dict[str, Any] | None]:
    """Get the debate-based hypothesis generation prompt.

    Multi-turn: experts discuss and refine hypotheses while the request's
    ``transcript`` accumulates; the final turn switches to
    schema-constrained JSON output.

    Args:
        req: The resolved debate-prompt request for this turn; its fields
            are documented on DebatePromptRequest.

    Returns:
        Tuple of (rendered prompt string, JSON schema dict or None).
    """
    return _render_debate_prompt(
        _build_debate_prompt_variables(req),
        req.articles_with_reasoning,
        req.is_final_turn,
    )
