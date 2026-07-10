"""Prompt builders for the debate-based hypothesis generation flow."""

from typing import Any

from co_scientist.prompts._common import (
    _format_meta_review_context,
    _format_run_guidance,
)
from co_scientist.prompts.generation_formatting import (
    _build_citation_reference_section,
    format_articles_metadata,
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
        focus_areas = generation_phase["focus_areas"]
        if isinstance(focus_areas, list):
            focus_areas = ", ".join(focus_areas)
        sections.append(f"Focus on: {focus_areas}\n")
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

    return "".join(sections) if sections else ""


_DEBATE_FINAL_TURN_INSTRUCTIONS = """

## FINAL TURN - OUTPUT FORMAT

This is the final turn of the debate. Based on the discussion above, output \
your finalized hypothesis in JSON format with all four required components:

### 1. hypothesis (required)
Dense technical description following "We want to develop [X] to enable [Y]" \
format (2-3 sentences).
- Include specific technical details: algorithms, mechanisms, mathematical \
formulations
- Be precise about what will be developed and the technical approach

Example: "We want to develop a 'Dynamic Velocity Sentinel'—which monitors the \
rate of change in latent activation directions across early-to-mid layers \
rather than static depths—to enable anticipatory gating that triggers only \
when precursor signals cross a 'point of no return' for danger features."

### 2. explanation (required)
Clear explanation for technical audiences in layman terms (4-6 sentences).
- Core problem being addressed
- Why key mechanisms work
- How components interact
- Practical advantages

Example: "This approach addresses the computational bottleneck by focusing on \
early layers where precursor signals first emerge. Rather than analyzing \
static magnitudes, the technique tracks velocity—the rate of change—which \
provides earlier detection of trajectories toward dangerous outputs. The \
system employs autoencoders to identify danger features, with dynamic gating \
that triggers only when trajectories cross a learned threshold."

### 3. literature_grounding (required)
Explicit grounding with inline citation keys (2-4 sentences).
- If a Citation Reference List was provided above, use ONLY those `[C*]` keys \
(e.g. `[C1]`, `[C2]`, `[C3]`)
- Do NOT invent author-year citations — only use keys from the list
- If no Citation Reference List was provided, state: "This hypothesis is \
formulated without access to a literature review."

Example: "This approach builds on sparse autoencoder analysis [C1] and circuit \
tracing [C2]. The velocity monitoring concept addresses a gap in \
static-analysis methods [C3][C4]."

### 4. experiment (required)
Concrete experiment design with models, datasets, methodology, metrics, and \
validation (4-6 sentences).

Example format: "Objective: Demonstrate that velocity monitoring achieves \
comparable detection with reduced cost. Models: GPT-2 Medium, pre-trained SAE \
layers 1-6. Datasets: AdvBench harmful prompts (500 examples), HH-RLHF benign \
prompts (1000 examples). Methodology: (1) Implement velocity tracking, (2) \
Train threshold detector, (3) Compare against baseline. Metrics: Detection \
accuracy, timing, false positive rate, computational overhead. Validation: \
Success requires >90% detection, <5% false positives, >50% cost reduction."

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


def _build_debate_prompt_variables(
    research_goal: str,
    hypotheses_count: int,
    transcript: str,
    preferences: str | None,
    attributes: str | list[str] | None,
    articles_with_reasoning: str | None,
    articles: list[Any] | None,
    reference_list: str,
    supervisor_guidance: dict[str, Any] | None,
    meta_review: dict[str, Any] | None,
    run_setup_guidance: str | None,
    run_focus_guidance: str | None,
    tool_registry: Any | None,
) -> dict[str, Any]:
    """Builds the template variables for the debate generation prompt.

    Args:
        research_goal: The research goal
        hypotheses_count: Number of hypotheses to generate
        transcript: Accumulated conversation transcript from previous turns
        preferences: Criteria for strong hypotheses
        attributes: Key attributes to prioritize
        articles_with_reasoning: Optional literature review synthesis for
            context
        articles: Optional list of Article objects for citation metadata
        reference_list: Optional citation reference list of `[C*]` keys
        supervisor_guidance: Optional guidance from supervisor
        meta_review: Optional cross-iteration meta-review feedback
        run_setup_guidance: Optional durable run setup guidance text
        run_focus_guidance: Optional durable run focus guidance text
        tool_registry: Optional ToolRegistry for dynamic tool instructions

    Returns:
        Dict of template variables for the debate generation prompt.
    """
    variables = {
        "goal": research_goal,
        "hypotheses_count": hypotheses_count,
        "transcript": transcript or "",
        "preferences": preferences
        or "Novel, testable, scientifically sound, specific, and diverse"
        " hypotheses",
        "attributes": _format_debate_attributes(attributes),
    }

    # Add literature review, article metadata, and citation context.
    variables.update(
        _build_debate_literature_variables(
            articles_with_reasoning, articles, reference_list
        )
    )

    # Format supervisor guidance if available
    variables["supervisor_guidance"] = _format_supervisor_guidance_for_debate(
        supervisor_guidance
    )

    # Add meta-review context if available (blank on iteration 1).
    variables["meta_review_context"] = _format_meta_review_context(meta_review)
    variables["run_guidance"] = _format_run_guidance(
        run_setup_guidance, run_focus_guidance
    )

    # Inject domain-specific prompt customizations
    variables.update(_get_domain_variables(tool_registry))

    return variables


def _render_debate_prompt(
    prompt_name: str,
    variables: dict[str, Any],
    is_final_turn: bool,
) -> tuple[str, dict[str, Any] | None]:
    """Render the debate prompt for one turn, given its resolved variables.

    Non-final turns are conversational and schema-less. The final turn is
    schema-constrained, with the JSON output instructions concatenated
    verbatim after the rendered template.

    Args:
        prompt_name: Prompt file stem to render.
        variables: Resolved template variables for this turn.
        is_final_turn: Whether this is the final turn of the debate.

    Returns:
        Tuple of (formatted prompt string, JSON schema dict or None).
    """
    if not is_final_turn:
        return load_prompt(prompt_name, variables), None

    prompt, schema = load_prompt_with_schema(prompt_name, variables)
    # Concatenated verbatim after the rendered template (never run through
    # substitute_variables), so the literal braces in the JSON example below
    # need no {{}} escaping.
    prompt = prompt + _DEBATE_FINAL_TURN_INSTRUCTIONS
    return prompt, schema


# Called by nodes/generation/debate.py once per debate turn. Template
# choice depends on literature availability
# (generation_debate_and_literature vs generation_after_debate), and the
# final turn switches from free-form discussion to schema-constrained JSON
# output (GENERATION_SCHEMA).
def get_debate_generation_prompt(
    research_goal: str,
    hypotheses_count: int,
    transcript: str,
    supervisor_guidance: dict[str, Any] | None = None,
    preferences: str | None = None,
    attributes: str | list[str] | None = None,
    is_final_turn: bool = False,
    articles_with_reasoning: str | None = None,
    articles: list[Any] | None = None,
    tool_registry: Any | None = None,
    reference_list: str = "",
    meta_review: dict[str, Any] | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the debate-based hypothesis generation prompt.

    This uses a multi-turn debate strategy where experts discuss and refine
    hypotheses.
    The transcript accumulates over multiple turns until final hypotheses are
    generated.

    Args:
        research_goal: The research goal
        hypotheses_count: Number of hypotheses to generate
        transcript: Accumulated conversation transcript from previous turns
        supervisor_guidance: Optional guidance from supervisor
        preferences: Criteria for strong hypotheses
        attributes: Key attributes to prioritize
        is_final_turn: Whether this is the final turn (outputs JSON schema)
        articles_with_reasoning: Optional literature review synthesis for
            context
        articles: Optional list of Article objects for citation metadata
        tool_registry: Optional ToolRegistry for dynamic tool instructions
        reference_list: Optional citation reference list of `[C*]` keys
        meta_review: Optional cross-iteration meta-review feedback
        run_setup_guidance: Optional durable run setup guidance text
        run_focus_guidance: Optional durable run focus guidance text

    Returns:
        Tuple of (formatted prompt string, JSON schema dict or None)
    """
    variables = _build_debate_prompt_variables(
        research_goal=research_goal,
        hypotheses_count=hypotheses_count,
        transcript=transcript,
        preferences=preferences,
        attributes=attributes,
        articles_with_reasoning=articles_with_reasoning,
        articles=articles,
        reference_list=reference_list,
        supervisor_guidance=supervisor_guidance,
        meta_review=meta_review,
        run_setup_guidance=run_setup_guidance,
        run_focus_guidance=run_focus_guidance,
        tool_registry=tool_registry,
    )

    # Determine which prompt to use based on literature availability
    prompt_name = (
        "generation_debate_and_literature"
        if articles_with_reasoning
        else "generation_after_debate"
    )

    return _render_debate_prompt(prompt_name, variables, is_final_turn)
