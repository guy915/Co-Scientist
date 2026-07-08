"""Supervisor node - create research plan and workflow guidance."""
# pylint: disable=inconsistent-quotes

import logging
from typing import Any

from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    MEDIUM_TEMPERATURE,
    PROGRESS_SUPERVISOR_START,
    PROGRESS_SUPERVISOR_COMPLETE,
)
from co_scientist.llm import call_llm_json
from co_scientist.models import create_metrics_update
from co_scientist.models import phase_message
from co_scientist.nodes.progress import emit_progress
from co_scientist.prompts import get_supervisor_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


async def supervisor_node(state: WorkflowState) -> dict[str, Any]:
    """Creates a research plan and provides workflow guidance.

    This node analyzes the research goal and configures an appropriate
    research plan, setting parameters and providing guidance for the
    entire workflow.

    Args:
        state: Current workflow state

    Returns:
        Dictionary with updated state fields (supervisor_guidance)
    """
    research_goal = state["research_goal"]
    logger.info("Supervisor analyzing research goal: %s...",
                research_goal[:100])

    # Extract optional user inputs from state
    preferences = state.get("preferences")
    attributes = state.get("attributes")
    constraints = state.get("constraints")
    criteria = state.get("criteria")
    user_hypotheses = state.get("starting_hypotheses")
    user_literature = state.get("literature")

    # Extract user configuration for workflow
    # These may be unset (None) if the run relies on engine defaults; the
    # prompt builder below falls back to "not specified" text in that case.
    initial_hypotheses_count = state.get("initial_hypotheses_count")
    max_iterations = state.get("max_iterations")
    evolution_max_count = state.get("evolution_max_count")
    mcp_available = bool(state.get("mcp_available", False))
    pubmed_available = bool(state.get("pubmed_available", False))

    # Emit progress
    # This is the first node in the graph, so this also marks the start of
    # the entire workflow from the UI's perspective.
    await emit_progress(state, "supervisor_start",
                        "Analyzing research goal and creating plan...",
                        PROGRESS_SUPERVISOR_START)

    # Call llm to create research plan with all context
    # mcp_available and pubmed_available let the prompt honestly describe
    # whether literature review will actually run, rather than assuming it
    # always will.
    prompt, schema = get_supervisor_prompt(
        research_goal=research_goal,
        preferences=preferences,
        attributes=attributes,
        constraints=constraints,
        user_hypotheses=user_hypotheses,
        user_literature=user_literature,
        initial_hypotheses_count=initial_hypotheses_count,
        max_iterations=max_iterations,
        evolution_max_count=evolution_max_count,
        mcp_available=mcp_available,
        pubmed_available=pubmed_available,
        tool_registry=state.get("tool_registry"),
        criteria=criteria,
        run_setup_guidance=state.get("run_setup_guidance"),
        run_focus_guidance=state.get("run_focus_guidance"),
    )

    # call_llm_json validates the response against schema, so downstream
    # nodes can trust supervisor_guidance has the expected shape without
    # re-checking types.
    response = await call_llm_json(
        prompt=prompt,
        model_name=state["supervisor_model_name"],
        max_tokens=EXTENDED_MAX_TOKENS,
        temperature=MEDIUM_TEMPERATURE,
        json_schema=schema,
        run_id=state.get("run_id"),
        prompt_name="supervisor",
        prompt_metadata={
            "prompt_length_chars": len(prompt),
        },
    )

    # Defensive .get() with empty-container defaults: even though the schema
    # constrains the LLM output, this keeps downstream consumers (generate,
    # debate, meta-review, etc.) safe from missing keys without needing their
    # own None-checks. This dict becomes state["supervisor_guidance"], the
    # steering context every later node reads to build its own prompts.
    supervisor_guidance = {
        "research_goal_analysis":
            response.get("research_goal_analysis", {}),
        "workflow_plan":
            response.get("workflow_plan", {}),
        "config_synthesis":
            response.get("config_synthesis", {}),
        "performance_assessment":
            response.get("performance_assessment", {}),
        "adjustment_recommendations":
            response.get("adjustment_recommendations", []),
        "output_preparation":
            response.get("output_preparation", {}),
    }

    logger.info("Supervisor plan created")

    # Log key insights from supervisor
    # Guard with isinstance since research_goal_analysis is only loosely
    # typed as dict[str, Any] and the LLM could in principle return an
    # unexpected shape despite the schema.
    goal_analysis = supervisor_guidance.get("research_goal_analysis", {})
    key_areas = goal_analysis.get("key_areas", []) if isinstance(
        goal_analysis, dict) else []
    if key_areas:
        logger.info("Key research areas identified: %s",
                    ', '.join(key_areas[:3]))

    # Emit progress
    # key_areas count is surfaced to the UI as extra context alongside the
    # phase completion.
    await emit_progress(state,
                        "supervisor_complete",
                        "Research plan created",
                        PROGRESS_SUPERVISOR_COMPLETE,
                        key_areas=len(key_areas))

    # Update metrics (deltas only, merge_metrics will add to existing state)
    # This node makes exactly one LLM call, so the delta is always 1.
    metrics = create_metrics_update(llm_calls_delta=1)

    return {
        "supervisor_guidance":
            supervisor_guidance,
        "metrics":
            metrics,
        "messages":
            phase_message("supervisor",
                          "Created research plan and workflow guidance",
                          key_areas=len(key_areas)),
    }
