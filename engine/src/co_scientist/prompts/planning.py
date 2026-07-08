"""Prompt builders for the supervisor, meta-review, and research-overview
nodes.
"""
# pylint: disable=inconsistent-quotes

from typing import Any

from co_scientist.prompts._common import _format_meta_review_context
from co_scientist.prompts._common import _format_run_guidance
from co_scientist.prompts.loading import _build_prompt


# Renders prompts/meta_review.md for nodes/meta_review.py; all_reviews is
# the JSON dump of every review collected so far, synthesized once per
# iteration into cross-hypothesis feedback.
def get_meta_review_prompt(
    research_goal: str,
    all_reviews: str,
    supervisor_guidance: dict[str, Any] | None = None,
    instructions: str | None = None,
    tool_registry: Any | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the meta-review synthesis prompt and schema."""
    return _build_prompt(
        "meta_review",
        {
            "research_goal": research_goal,
            "all_reviews": all_reviews,
            "instructions": instructions or "",
        },
        supervisor_guidance=_format_supervisor_guidance_for_meta_review(
            supervisor_guidance),
        run_guidance=_format_run_guidance(run_setup_guidance,
                                          run_focus_guidance),
        tool_registry=tool_registry,
    )


# Renders prompts/research_overview.md for nodes/research_overview.py, the
# terminal synthesis over the top-Elo hypotheses.
def get_research_overview_prompt(
    research_goal: str,
    hypotheses_summary: str,
    meta_review: dict[str, Any] | None = None,
    tool_registry: Any | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the research-overview + NIH Specific Aims prompt and schema."""
    return _build_prompt(
        "research_overview",
        {
            "research_goal": research_goal,
            "hypotheses_summary": hypotheses_summary,
        },
        meta_review_context=_format_meta_review_context(meta_review),
        run_guidance=_format_run_guidance(run_setup_guidance,
                                          run_focus_guidance),
        tool_registry=tool_registry,
    )


# Renders prompts/supervisor.md for nodes/supervisor.py, the planning call
# at the head of the graph. Every user-supplied run input (preferences,
# constraints, seed hypotheses/literature, count knobs) is normalized to a
# "None provided"/"not specified" string so the template never renders a
# raw Python None.
def get_supervisor_prompt(
    research_goal: str,
    preferences: str | None = None,
    attributes: list[str] | None = None,
    constraints: list[str] | None = None,
    user_hypotheses: list[str] | None = None,
    user_literature: list[str] | None = None,
    initial_hypotheses_count: int | None = None,
    max_iterations: int | None = None,
    evolution_max_count: int | None = None,
    mcp_available: bool = False,
    pubmed_available: bool = False,
    tool_registry: Any | None = None,
    criteria: list[str] | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """get the supervisor research planning prompt and schema."""

    # Build pipeline description based on available tools
    lit_review_description = ""
    if pubmed_available or mcp_available:
        lit_review_description = (
            "literature review will search pubmed for relevant papers"
            " and analyze them")
    else:
        lit_review_description = (
            "literature review is not available (no pubmed access)")

    variables = {
        "research_goal": research_goal,
        "preferences": preferences or "None provided",
        "attributes": ", ".join(attributes) if attributes else "None provided",
        "constraints": ("\n".join(
            f"- {c}" for c in constraints) if constraints else "None provided"),
        "criteria": ("\n".join(
            f"- {c}" for c in criteria) if criteria else "None provided"),
        "user_hypotheses": ("\n".join(f"- {h}" for h in user_hypotheses)
                            if user_hypotheses else "None provided"),
        "user_literature": ("\n".join(f"- {lit}" for lit in user_literature)
                            if user_literature else "None provided"),
        "initial_hypotheses_count": initial_hypotheses_count or "not specified",
        "max_iterations": max_iterations or "not specified",
        "evolution_max_count": evolution_max_count or "not specified",
        "literature_review_description": lit_review_description,
    }

    return _build_prompt(
        "supervisor",
        variables,
        run_guidance=_format_run_guidance(run_setup_guidance,
                                          run_focus_guidance),
        tool_registry=tool_registry,
    )


def _format_supervisor_guidance_for_meta_review(
        supervisor_guidance: dict[str, Any] | None) -> str:
    """Format supervisor guidance for meta-review prompts."""
    if not supervisor_guidance or not isinstance(supervisor_guidance, dict):
        return ""

    sections = []
    sections.append("## Supervisor Guidance\n")

    # Add key research areas
    goal_analysis = supervisor_guidance.get("research_goal_analysis", {})
    key_areas = goal_analysis.get("key_areas", [])
    if key_areas:
        sections.append("**Key Research Areas:**\n")
        for area in key_areas:
            sections.append(f"- {area}\n")
        sections.append("\n")

    # Add evolution phase guidance
    workflow_plan = supervisor_guidance.get("workflow_plan", {})
    evolution_phase = workflow_plan.get("evolution_phase", {})
    if evolution_phase:
        sections.append("**Evolution Phase Guidance:**\n")
        if evolution_phase.get("refinement_priorities"):
            priorities = evolution_phase["refinement_priorities"]
            if isinstance(priorities, list):
                priorities = ", ".join(priorities)
            sections.append(f"- Refinement Priorities: {priorities}\n")
        if evolution_phase.get("iteration_strategy"):
            iter_strat = evolution_phase['iteration_strategy']
            sections.append(f"- Iteration Strategy: {iter_strat}\n")
        sections.append("\n")

    sections.append(
        "Use this guidance to ensure your meta-review synthesis aligns"
        " with the research plan and evolution strategy.\n")

    return "".join(sections) if sections else ""
