# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Supervisor node - create research plan and workflow guidance."""
# pylint: disable=inconsistent-quotes

import logging
from typing import Any, Dict

from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    MEDIUM_TEMPERATURE,
    PROGRESS_SUPERVISOR_START,
    PROGRESS_SUPERVISOR_COMPLETE,
)
from co_scientist.llm import call_llm_json
from co_scientist.models import create_metrics_update
from co_scientist.prompts import get_supervisor_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


async def supervisor_node(state: WorkflowState) -> Dict[str, Any]:
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

    # extract optional user inputs from state
    preferences = state.get("preferences")
    attributes = state.get("attributes")
    constraints = state.get("constraints")
    user_hypotheses = state.get("starting_hypotheses")
    user_literature = state.get("literature")

    # extract user configuration for workflow
    initial_hypotheses_count = state.get("initial_hypotheses_count")
    max_iterations = state.get("max_iterations")
    evolution_max_count = state.get("evolution_max_count")
    mcp_available = bool(state.get("mcp_available", False))
    pubmed_available = bool(state.get("pubmed_available", False))

    # emit progress
    progress_callback = state.get("progress_callback")
    if progress_callback is not None:
        await progress_callback(
            "supervisor_start",
            {
                "message": "Analyzing research goal and creating plan...",
                "progress": PROGRESS_SUPERVISOR_START,
            },
        )

    # call llm to create research plan with all context
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
    )

    # save prompt to disk for debugging
    from co_scientist.prompts import save_prompt_to_disk  # pylint: disable=import-outside-toplevel

    save_prompt_to_disk(
        run_id=state.get("run_id", "unknown"),
        prompt_name="supervisor",
        content=prompt,
        metadata={
            "prompt_length_chars": len(prompt),
        },
    )

    response = await call_llm_json(
        prompt=prompt,
        model_name=state["supervisor_model_name"],
        max_tokens=EXTENDED_MAX_TOKENS,
        temperature=MEDIUM_TEMPERATURE,
        json_schema=schema,
    )

    supervisor_guidance = {
        "research_goal_analysis":
            response.get("research_goal_analysis", {}),
        "workflow_plan":
            response.get("workflow_plan", {}),
        "performance_assessment":
            response.get("performance_assessment", {}),
        "adjustment_recommendations":
            response.get("adjustment_recommendations", []),
        "output_preparation":
            response.get("output_preparation", {}),
    }

    logger.info("Supervisor plan created")

    # Log key insights from supervisor
    goal_analysis = supervisor_guidance.get("research_goal_analysis", {})
    key_areas = goal_analysis.get("key_areas", []) if isinstance(
        goal_analysis, dict) else []
    if key_areas:
        logger.info("Key research areas identified: %s",
                    ', '.join(key_areas[:3]))

    # Emit progress
    progress_callback = state.get("progress_callback")
    if progress_callback is not None:
        await progress_callback(
            "supervisor_complete",
            {
                "message": "Research plan created",
                "progress": PROGRESS_SUPERVISOR_COMPLETE,
                "key_areas": len(key_areas),
            },
        )

    # Update metrics (deltas only, merge_metrics will add to existing state)
    metrics = create_metrics_update(llm_calls_delta=1)

    return {
        "supervisor_guidance":
            supervisor_guidance,
        "metrics":
            metrics,
        "messages": [{
            "role": "assistant",
            "content": "Created research plan and workflow guidance",
            "metadata": {
                "phase": "supervisor",
                "key_areas": len(key_areas)
            },
        }],
    }
