"""Prompt builders for the planning-oriented nodes.

Covers the supervisor, meta-review, and research-overview nodes.
"""

from dataclasses import dataclass
from typing import Any

from co_scientist.prompts._common import (
    PromptRunContext,
    PromptSections,
    _format_bullet_list,
    _format_bullet_section,
    _format_csv_list,
    _format_meta_review_context,
    _run_guidance_section,
)
from co_scientist.prompts.loading import _build_prompt


# Renders prompts/meta_review.md for nodes/meta_review.py; all_reviews is
# the JSON dump of every review collected so far, synthesized once per
# iteration into cross-hypothesis feedback.
def get_meta_review_prompt(
    research_goal: str,
    all_reviews: str,
    instructions: str | None = None,
    context: PromptRunContext | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the meta-review synthesis prompt and schema.

    Args:
        research_goal: The run's research goal.
        all_reviews: JSON dump of every review collected so far.
        instructions: Optional extra synthesis instructions.
        context: Run-scoped prompt context (supervisor guidance, tool
            registry, run setup/focus guidance).

    Returns:
        Tuple of (rendered prompt string, JSON schema dict or None).
    """
    ctx = context or PromptRunContext()
    return _build_prompt(
        "meta_review",
        {
            "research_goal": research_goal,
            "all_reviews": all_reviews,
            "instructions": instructions or "",
        },
        sections=PromptSections(
            supervisor_guidance=_format_supervisor_guidance_for_meta_review(
                ctx.supervisor_guidance
            ),
            run_guidance=_run_guidance_section(ctx),
        ),
        tool_registry=ctx.tool_registry,
    )


# Renders prompts/research_overview.md for nodes/research_overview.py, the
# terminal synthesis over the top-Elo hypotheses.
def get_research_overview_prompt(
    research_goal: str,
    hypotheses_summary: str,
    contact_candidates: str = "No verified literature authors available.",
    evidence_corpus: str = "No verified evidence corpus available.",
    context: PromptRunContext | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the research-overview + NIH Specific Aims prompt and schema.

    Args:
        research_goal: The run's research goal.
        hypotheses_summary: Formatted summary of the top-Elo hypotheses.
        contact_candidates: Verified literature authors, pre-formatted.
        evidence_corpus: Analyzed sources, pre-formatted.
        context: Run-scoped prompt context (meta-review, tool registry,
            run setup/focus guidance).

    Returns:
        Tuple of (rendered prompt string, JSON schema dict or None).
    """
    ctx = context or PromptRunContext()
    return _build_prompt(
        "research_overview",
        {
            "research_goal": research_goal,
            "hypotheses_summary": hypotheses_summary,
            "contact_candidates": contact_candidates,
            "evidence_corpus": evidence_corpus,
        },
        sections=PromptSections(
            meta_review_context=_format_meta_review_context(ctx.meta_review),
            run_guidance=_run_guidance_section(ctx),
        ),
        tool_registry=ctx.tool_registry,
    )


def _format_lit_review_description(
    mcp_available: bool, pubmed_available: bool
) -> str:
    """Describe literature-review availability for the supervisor prompt."""
    if pubmed_available or mcp_available:
        return (
            "literature review will search pubmed for relevant papers"
            " and analyze them"
        )
    return "literature review is not available (no pubmed access)"


@dataclass(frozen=True)
class SupervisorPromptInputs:
    """The run inputs the supervisor plans against.

    Attributes:
        research_goal: The run's research goal.
        preferences: Free-text user preferences, if any.
        attributes: Desired hypothesis attributes.
        constraints: User-supplied run constraints.
        criteria: User-supplied evaluation criteria.
        user_hypotheses: Seed hypotheses supplied by the user.
        user_literature: Seed literature supplied by the user.
        initial_hypotheses_count: Requested first-wave hypothesis count.
        max_iterations: Requested maximum workflow iterations.
        evolution_max_count: Requested maximum evolved hypotheses.
        mcp_available: Whether an MCP server is reachable.
        pubmed_available: Whether PubMed search is reachable.
    """

    research_goal: str
    preferences: str | None = None
    attributes: list[str] | None = None
    constraints: list[str] | None = None
    criteria: list[str] | None = None
    user_hypotheses: list[str] | None = None
    user_literature: list[str] | None = None
    initial_hypotheses_count: int | None = None
    max_iterations: int | None = None
    evolution_max_count: int | None = None
    mcp_available: bool = False
    pubmed_available: bool = False


def _build_supervisor_prompt_variables(
    inputs: SupervisorPromptInputs,
) -> dict[str, Any]:
    """Build the template variables for the supervisor planning prompt.

    Every user-supplied run input (preferences, constraints, seed
    hypotheses/literature, count knobs) is normalized to a "None
    provided"/"not specified" string so the template never renders a raw
    Python None.

    Args:
        inputs: The run inputs the supervisor plans against.

    Returns:
        Dict of template variables for the supervisor prompt.
    """
    return {
        "research_goal": inputs.research_goal,
        "preferences": inputs.preferences or "None provided",
        "attributes": _format_csv_list(inputs.attributes),
        "constraints": _format_bullet_list(inputs.constraints),
        "criteria": _format_bullet_list(inputs.criteria),
        "user_hypotheses": _format_bullet_list(inputs.user_hypotheses),
        "user_literature": _format_bullet_list(inputs.user_literature),
        "initial_hypotheses_count": (
            inputs.initial_hypotheses_count or "not specified"
        ),
        "max_iterations": inputs.max_iterations or "not specified",
        "evolution_max_count": inputs.evolution_max_count or "not specified",
        "literature_review_description": _format_lit_review_description(
            inputs.mcp_available, inputs.pubmed_available
        ),
    }


# Renders prompts/supervisor.md for nodes/supervisor.py, the planning call
# at the head of the graph.
def get_supervisor_prompt(
    inputs: SupervisorPromptInputs,
    context: PromptRunContext | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the supervisor research planning prompt and schema.

    Args:
        inputs: The run inputs the supervisor plans against.
        context: Run-scoped prompt context (tool registry, run setup/focus
            guidance).

    Returns:
        Tuple of (rendered prompt string, JSON schema dict or None).
    """
    ctx = context or PromptRunContext()
    return _build_prompt(
        "supervisor",
        _build_supervisor_prompt_variables(inputs),
        sections=PromptSections(run_guidance=_run_guidance_section(ctx)),
        tool_registry=ctx.tool_registry,
    )


def _format_meta_review_evolution_phase_section(
    evolution_phase: dict[str, Any],
) -> list[str]:
    """Format the evolution-phase slice of meta-review supervisor guidance."""
    if not evolution_phase:
        return []

    sections = ["**Evolution Phase Guidance:**\n"]
    if evolution_phase.get("refinement_priorities"):
        priorities = evolution_phase["refinement_priorities"]
        if isinstance(priorities, list):
            priorities = ", ".join(priorities)
        sections.append(f"- Refinement Priorities: {priorities}\n")
    if evolution_phase.get("iteration_strategy"):
        iter_strat = evolution_phase["iteration_strategy"]
        sections.append(f"- Iteration Strategy: {iter_strat}\n")
    sections.append("\n")
    return sections


def _format_supervisor_guidance_for_meta_review(
    supervisor_guidance: dict[str, Any] | None,
) -> str:
    """Format supervisor guidance for meta-review prompts."""
    if not supervisor_guidance or not isinstance(supervisor_guidance, dict):
        return ""

    goal_analysis = supervisor_guidance.get("research_goal_analysis", {})
    workflow_plan = supervisor_guidance.get("workflow_plan", {})

    sections = ["## Supervisor Guidance\n"]
    sections.append(
        _format_bullet_section(
            "Key Research Areas", goal_analysis.get("key_areas", [])
        )
    )
    sections.extend(
        _format_meta_review_evolution_phase_section(
            workflow_plan.get("evolution_phase", {})
        )
    )
    sections.append(
        "Use this guidance to ensure your meta-review synthesis aligns"
        " with the research plan and evolution strategy.\n"
    )

    return "".join(sections) if sections else ""
