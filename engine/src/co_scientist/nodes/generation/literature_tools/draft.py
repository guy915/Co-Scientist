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
"""Phase 1: Draft hypotheses by reading papers and identifying gaps.

This is the first phase of tool-based generation. The agent reads pre-curated
papers using tools and drafts initial hypothesis ideas based on identified gaps.
"""

import hashlib
import logging
from typing import Any, Optional, TYPE_CHECKING

from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    HIGH_TEMPERATURE,
    get_draft_max_iterations,
)
from co_scientist.exceptions import ResponseParseError
from co_scientist.llm import call_llm_with_tools, attempt_json_repair
from co_scientist.prompts import get_draft_prompt_with_tools
from co_scientist.state import WorkflowState
from co_scientist.tools.literature import literature_tools
from co_scientist.tools.provider import HybridToolProvider

if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry

logger = logging.getLogger(__name__)


async def draft_hypotheses(
    state: WorkflowState,
    count: int,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"] = None,
    reference_index: Any | None = None,
) -> list[dict[str, str]]:
    """Phase 1: draft hypotheses by searching literature sources for metadata.

    Uses tools for searching research literature.
    Tool whitelist is determined from tool_registry if provided,
    otherwise falls back to hardcoded default.

    Args:
        state: Current workflow state
        count: Number of hypotheses to draft
        mcp_client: MCP client for tool access
        tool_registry: Optional ToolRegistry for config-driven tool selection
        reference_index: Optional citation reference index supplying the
            `[C*]` reference list

    Returns:
        List of draft dicts with text, gap_reasoning, literature_sources
    """
    logger.info("Phase 1: Drafting %s hypotheses by examining literature",
                count)

    # get state variables
    supervisor_guidance = state.get("supervisor_guidance", {})
    articles_with_reasoning = state.get("articles_with_reasoning")
    preferences = state.get("preferences")
    attributes = state.get("attributes")
    user_hypotheses = state.get("starting_hypotheses")
    articles = state.get("articles") or []

    # create shared slug for corpus (reuse lit review slug for warm start)
    research_goal = state["research_goal"]
    shared_slug = "research_" + hashlib.md5(
        research_goal.encode()).hexdigest()[:8]
    logger.info("Using shared corpus slug: %s", shared_slug)

    # store slug in state for validation phase to reuse
    state["generation_corpus_slug"] = shared_slug

    # log lit review context
    if articles_with_reasoning:
        logger.info("Including lit review summary as context for drafting")
        logger.info(
            "Warm start: corpus already populated with %s papers"
            " from literature review", len(articles))
    else:
        logger.warning("No lit review summary available"
                       " - agent will examine papers directly")

    # initialize hybrid tool provider with draft-specific whitelist
    provider = HybridToolProvider(mcp_client=mcp_client,
                                  python_registry=literature_tools)

    # get tool whitelist from registry or try global registry
    if tool_registry is None:
        try:
            from co_scientist.config import get_tool_registry  # pylint: disable=import-outside-toplevel

            tool_registry = get_tool_registry()
            logger.info("Using global tool registry")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to get tool registry: %s", e)

    if tool_registry:
        tool_ids = tool_registry.get_tools_for_workflow("draft_generation")
        mcp_whitelist = tool_registry.get_mcp_tool_names(tool_ids)
        logger.info("Using tool registry whitelist: %s", mcp_whitelist)
    else:
        # no registry available - let provider use all available tools
        mcp_whitelist = None
        logger.warning("No tool registry - using all available MCP tools")

    python_whitelist: list[str] = []

    tools_dict, openai_tools = provider.get_tools(
        mcp_whitelist=mcp_whitelist, python_whitelist=python_whitelist)

    logger.info("Initialized draft provider with %s tools", len(tools_dict))

    # calculate dynamic iteration budget based on hypotheses count
    max_iterations = get_draft_max_iterations(count)
    logger.info("Draft budget: %s iterations for %s hypotheses", max_iterations,
                count)

    # build draft prompt with lit review summary as context
    ref_text = reference_index.text if reference_index else ""
    prompt, _ = get_draft_prompt_with_tools(
        research_goal=state["research_goal"],
        hypotheses_count=count,
        supervisor_guidance=supervisor_guidance,
        articles=articles,
        articles_with_reasoning=articles_with_reasoning,
        preferences=preferences,
        attributes=attributes,
        user_hypotheses=user_hypotheses,
        max_iterations=max_iterations,
        tool_registry=tool_registry,
        reference_list=ref_text,
    )

    # save prompt to disk
    from co_scientist.prompts import save_prompt_to_disk  # pylint: disable=import-outside-toplevel

    save_prompt_to_disk(
        run_id=state.get("run_id", "unknown"),
        prompt_name="generate_draft_with_tools",
        content=prompt,
        metadata={
            "hypotheses_count": count,
            "max_iterations": max_iterations,
            "prompt_length_chars": len(prompt),
        },
    )

    # track tool calls in draft phase
    tool_call_counts: dict[str, int] = {}

    # create tracked executor for draft phase
    async def draft_tracked_executor(tool_call: Any) -> dict[str, Any]:
        """Track and execute tool calls for draft phase."""
        tool_name = tool_call.function.name

        # track all tool calls
        tool_call_counts[tool_name] = tool_call_counts.get(tool_name, 0) + 1
        call_num = tool_call_counts[tool_name]
        logger.info("Draft: %s call #%s", tool_name, call_num)

        # execute tool
        return await provider.execute_tool_call(tool_call)

    # call LLM with tools for drafting
    # scale token budget based on hypotheses count (~200 tokens per hypothesis)
    draft_max_tokens = min(EXTENDED_MAX_TOKENS + (count * 200), 16000)
    logger.info("Calling draft agent: %s iterations, %s max tokens",
                max_iterations, draft_max_tokens)

    try:
        final_response, _ = await call_llm_with_tools(
            prompt=prompt,
            model_name=state["model_name"],
            tools=openai_tools,
            tool_executor=draft_tracked_executor,
            max_tokens=draft_max_tokens,
            temperature=HIGH_TEMPERATURE,
            max_iterations=max_iterations,
        )
    except Exception as e:
        logger.error("Draft phase failed: %s", e)
        raise

    total_calls = sum(tool_call_counts.values())
    calls_summary = ", ".join(
        f"{name}={count}" for name, count in tool_call_counts.items())
    logger.info("Draft phase complete: %s tool calls (%s)", total_calls,
                calls_summary)

    # parse JSON response (strip markdown if present, then use repair logic)
    response_text = final_response.strip()

    # handle markdown code blocks (case-insensitive)
    response_lower = response_text.lower()
    if "```json" in response_lower:
        # find ```json (case-insensitive)
        start_idx = response_lower.find("```json")
        json_start = start_idx + 7  # length of "```json"
        # find closing ``` after the opening
        json_end = response_text.find("```", json_start)
        if json_end == -1:
            # no closing ``` found, use rest of text
            response_text = response_text[json_start:].strip()
        else:
            response_text = response_text[json_start:json_end].strip()
    elif "```" in response_text:
        # plain code block without "json"
        json_start = response_text.find("```") + 3
        json_end = response_text.find("```", json_start)
        if json_end == -1:
            response_text = response_text[json_start:].strip()
        else:
            response_text = response_text[json_start:json_end].strip()

    # additional cleanup - remove leading/trailing whitespace and newlines
    response_text = response_text.strip().strip("\n").strip()

    # use attempt_json_repair for robust parsing
    response_data, was_repaired = attempt_json_repair(response_text,
                                                      allow_major_repairs=True)

    if response_data is None:
        logger.error(
            "Failed to parse draft JSON response after all repair attempts")
        logger.error("Response: %s...", final_response[:500])
        raise ResponseParseError(
            "Draft phase returned invalid JSON that could not be repaired")

    if was_repaired:
        logger.warning(
            "Draft JSON response required major repairs (possible truncation)")

    drafts: list[dict[str, str]] = response_data.get("drafts", [])
    logger.info("Parsed %s draft hypotheses", len(drafts))
    return drafts
