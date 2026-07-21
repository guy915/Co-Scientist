"""Supervisor node - create research plan and workflow guidance."""

import logging
from typing import Any

from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    MEDIUM_TEMPERATURE,
    PROGRESS_SUPERVISOR_COMPLETE,
    PROGRESS_SUPERVISOR_START,
)
from co_scientist.llm import call_llm_json
from co_scientist.models import create_metrics_update, phase_message
from co_scientist.progress import emit_progress
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
    prompt_context = _extract_supervisor_context(state)
    research_goal = prompt_context["research_goal"]
    logger.info(
        "Supervisor analyzing research goal: %s...", research_goal[:100]
    )

    # Emit progress
    # This is the first node in the graph, so this also marks the start of
    # the entire workflow from the UI's perspective.
    await emit_progress(
        state,
        "supervisor_start",
        "Analyzing research goal and creating plan...",
        PROGRESS_SUPERVISOR_START,
    )

    # Call llm to create research plan with all context
    prompt, schema = get_supervisor_prompt(**prompt_context)
    response = await _call_supervisor_llm(state, prompt, schema)
    supervisor_guidance = _build_supervisor_guidance(response)

    logger.info("Supervisor plan created")

    # Log key insights from supervisor
    key_areas = _extract_key_areas(supervisor_guidance)
    if key_areas:
        logger.info(
            "Key research areas identified: %s", ", ".join(key_areas[:3])
        )

    # Emit progress
    # key_areas count is surfaced to the UI as extra context alongside the
    # phase completion.
    await emit_progress(
        state,
        "supervisor_complete",
        "Research plan created",
        PROGRESS_SUPERVISOR_COMPLETE,
        key_areas=len(key_areas),
    )

    return _build_supervisor_result(supervisor_guidance, key_areas)


async def _call_supervisor_llm(
    state: WorkflowState, prompt: str, schema: dict[str, Any] | None
) -> dict[str, Any]:
    """Calls the LLM to generate the supervisor's research plan.

    call_llm_json validates the response against schema, so downstream
    nodes can trust supervisor_guidance has the expected shape without
    re-checking types.

    Args:
        state: Current workflow state.
        prompt: Rendered supervisor prompt.
        schema: JSON schema the response must conform to.

    Returns:
        The raw LLM JSON response.
    """
    return await call_llm_json(
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


def _build_supervisor_result(
    supervisor_guidance: dict[str, Any], key_areas: list[str]
) -> dict[str, Any]:
    """Assembles the supervisor_node return dict.

    Args:
        supervisor_guidance: Assembled supervisor_guidance dict.
        key_areas: Key research areas extracted from supervisor_guidance,
            reused here for the phase_message metadata.

    Returns:
        Dict with updated state fields (supervisor_guidance, metrics,
        messages).
    """
    # Update metrics (deltas only, merge_metrics will add to existing state)
    # This node makes exactly one LLM call, so the delta is always 1.
    metrics = create_metrics_update(llm_calls_delta=1)

    return {
        "supervisor_guidance": supervisor_guidance,
        "metrics": metrics,
        "messages": phase_message(
            "supervisor",
            "Created research plan and workflow guidance",
            key_areas=len(key_areas),
        ),
    }


def _extract_supervisor_context(state: WorkflowState) -> dict[str, Any]:
    """Extracts the state fields needed to build the supervisor prompt.

    Groups the field-by-field state access into one place so
    supervisor_node stays focused on orchestration. Most fields are
    optional (None) if the run relies on engine defaults; the prompt
    builder falls back to "not specified" text in that case. mcp_available
    and pubmed_available let the prompt honestly describe whether
    literature review will actually run, rather than assuming it always
    will.

    Args:
        state: Current workflow state.

    Returns:
        Dict of keyword arguments ready to spread into
        get_supervisor_prompt.
    """
    return {
        "research_goal": state["research_goal"],
        "preferences": state.get("preferences"),
        "attributes": state.get("attributes"),
        "constraints": state.get("constraints"),
        "user_hypotheses": state.get("starting_hypotheses"),
        "user_literature": state.get("literature"),
        "initial_hypotheses_count": state.get("initial_hypotheses_count"),
        "max_iterations": state.get("max_iterations"),
        "evolution_max_count": state.get("evolution_max_count"),
        "mcp_available": bool(state.get("mcp_available", False)),
        "pubmed_available": bool(state.get("pubmed_available", False)),
        "tool_registry": state.get("tool_registry"),
        "criteria": state.get("criteria"),
        "run_setup_guidance": state.get("run_setup_guidance"),
        "run_focus_guidance": state.get("run_focus_guidance"),
    }


def _extract_key_areas(supervisor_guidance: dict[str, Any]) -> list[str]:
    """Pulls the identified key research areas out of supervisor guidance.

    Guards with isinstance since research_goal_analysis is only loosely
    typed as dict[str, Any] and the LLM could in principle return an
    unexpected shape despite the schema.

    Args:
        supervisor_guidance: assembled supervisor_guidance dict.

    Returns:
        The key_areas list, or an empty list if absent/malformed.
    """
    goal_analysis = supervisor_guidance.get("research_goal_analysis", {})
    if not isinstance(goal_analysis, dict):
        return []
    key_areas: list[str] = goal_analysis.get("key_areas", [])
    return key_areas


def _build_supervisor_guidance(response: dict[str, Any]) -> dict[str, Any]:
    """Assembles the supervisor_guidance state dict from the LLM response.

    Uses defensive .get() with empty-container defaults: even though the
    schema constrains the LLM output, this keeps downstream consumers
    (generate, debate, meta-review, etc.) safe from missing keys without
    needing their own None-checks. The result becomes
    state["supervisor_guidance"], the steering context every later node
    reads to build its own prompts.

    Args:
        response: raw LLM JSON response from the supervisor call.

    Returns:
        The assembled supervisor_guidance dict.
    """
    return {
        "research_goal_analysis": response.get("research_goal_analysis", {}),
        "workflow_plan": response.get("workflow_plan", {}),
        "config_synthesis": response.get("config_synthesis", {}),
        "performance_assessment": response.get("performance_assessment", {}),
        "adjustment_recommendations": response.get(
            "adjustment_recommendations", []
        ),
        "output_preparation": response.get("output_preparation", {}),
    }
