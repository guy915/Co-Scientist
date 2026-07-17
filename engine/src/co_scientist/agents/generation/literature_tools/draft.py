"""Phase 1: Draft hypotheses by reading papers and identifying gaps.

This is the first phase of tool-based generation. The agent reads pre-curated
papers using tools and drafts initial hypothesis ideas based on identified gaps.
"""

import logging
from typing import TYPE_CHECKING, Any, Optional

from co_scientist.constants import (
    DRAFT_MAX_TOKENS_CAP,
    DRAFT_TOKENS_PER_HYPOTHESIS,
    EXTENDED_MAX_TOKENS,
    HIGH_TEMPERATURE,
    corpus_slug,
    get_draft_max_iterations,
    scaled_max_tokens,
)
from co_scientist.exceptions import ResponseParseError
from co_scientist.llm import call_llm_with_tools
from co_scientist.llm_json import attempt_json_repair, extract_response_json
from co_scientist.prompts import get_draft_prompt_with_tools
from co_scientist.state import WorkflowState
from co_scientist.tools.provider import MCPToolProvider

if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry

logger = logging.getLogger(__name__)


def _log_lit_review_context(
    articles_with_reasoning: str | None, articles: list[Any]
) -> None:
    """Log whether warm-started literature-review context is available.

    Args:
        articles_with_reasoning: lit review summary text, if any.
        articles: articles already fetched by the literature review (used to
            report the warm-start paper count).
    """
    if articles_with_reasoning:
        logger.info("Including lit review summary as context for drafting")
        logger.info(
            "Warm start: corpus already populated with %s papers"
            " from literature review",
            len(articles),
        )
    else:
        logger.warning(
            "No lit review summary available"
            " - agent will examine papers directly"
        )


def _setup_tool_provider(
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    workflow_name: str,
    label: str,
    log: logging.Logger,
) -> tuple[MCPToolProvider, list[Any], Optional["ToolRegistry"]]:
    """Resolve the tool registry/whitelist and init an MCP tool provider.

    Shared by the draft phase here and the validation synthesis stage
    (validate_synthesis.py). Fallback chain: passed-in registry (threaded
    from WorkflowState) -> process-global registry (covers standalone/dev
    scripts that never thread one through state) -> no whitelist at all
    (provider uses every available tool).

    Args:
        mcp_client: MCP client for tool access.
        tool_registry: optional ToolRegistry for config-driven tool
            selection; resolved from the global registry when None.
        workflow_name: registry workflow key selecting the tool whitelist.
        label: short phase label used in log messages.
        log: the calling module's logger, so log records keep their
            per-phase attribution.

    Returns:
        Tuple of (provider, openai_tools, resolved tool_registry).
    """
    if tool_registry is None:
        try:
            # Imported at call time so tests can monkeypatch
            # config.get_tool_registry on the config module namespace.
            from co_scientist.config import (
                get_tool_registry,
            )

            tool_registry = get_tool_registry()
            log.info("Using global tool registry for %s", label)
        except Exception as e:
            log.warning("Failed to get tool registry: %s", e)

    provider = MCPToolProvider(mcp_client=mcp_client)

    if tool_registry:
        tool_ids = tool_registry.get_tools_for_workflow(workflow_name)
        mcp_whitelist = tool_registry.get_mcp_tool_names(tool_ids)
        log.info("Tool whitelist for %s: %s", label, mcp_whitelist)
    else:
        # No registry available - let provider use all available tools
        mcp_whitelist = None
        log.warning("No tool registry - using all available MCP tools")

    tools_dict, openai_tools = provider.get_tools(mcp_whitelist=mcp_whitelist)
    log.info("Initialized %s provider with %s tools", label, len(tools_dict))

    return provider, openai_tools, tool_registry


def _parse_draft_response(final_response: str) -> list[dict[str, str]]:
    """Parse the draft agent's final response into draft hypothesis dicts.

    Args:
        final_response: the draft agent's final tool-call-loop response.

    Returns:
        List of draft dicts with text, gap_reasoning, literature_sources.

    Raises:
        ResponseParseError: if the response cannot be parsed as JSON even
            after repair attempts.
    """
    # Parse JSON response (strip markdown if present, then use repair logic)
    response_text = extract_response_json(final_response)

    # Use attempt_json_repair for robust parsing
    # allow_major_repairs=True: tool-calling loop final responses are more
    # prone to truncated/malformed JSON than single-shot calls (llm.py).
    response_data, was_repaired = attempt_json_repair(
        response_text, allow_major_repairs=True
    )

    if response_data is None:
        logger.error(
            "Failed to parse draft JSON response after all repair attempts"
        )
        logger.error("Response: %s...", final_response[:500])
        # Hard failure instead of returning an empty draft list: silently
        # skipping to an empty Phase 1 would make Phase 2 a silent no-op too.
        raise ResponseParseError(
            "Draft phase returned invalid JSON that could not be repaired"
        )

    if was_repaired:
        logger.warning(
            "Draft JSON response required major repairs (possible truncation)"
        )

    drafts: list[dict[str, str]] = response_data.get("drafts", [])
    logger.info("Parsed %s draft hypotheses", len(drafts))
    return drafts


def _build_draft_prompt(
    state: WorkflowState,
    count: int,
    max_iterations: int,
    tool_registry: Optional["ToolRegistry"],
    reference_index: Any | None,
) -> str:
    """Assemble the Phase 1 draft prompt from workflow state and context.

    Args:
        state: Current workflow state.
        count: Number of hypotheses to draft.
        max_iterations: Iteration budget already computed for this draft
            call.
        tool_registry: Resolved ToolRegistry for config-driven tool
            selection.
        reference_index: Optional citation reference index supplying the
            `[C*]` reference list.

    Returns:
        The assembled draft prompt text.
    """
    # Get state variables
    supervisor_guidance = state.get("supervisor_guidance", {})
    meta_review = state.get("meta_review")
    articles_with_reasoning = state.get("articles_with_reasoning")
    preferences = state.get("preferences")
    attributes = state.get("attributes")
    user_hypotheses = state.get("starting_hypotheses")
    articles = state.get("articles") or []

    # Shared slug for corpus (reuse lit review slug for warm start); the
    # validation phase derives the same slug from the research goal.
    research_goal = state["research_goal"]
    shared_slug = corpus_slug(research_goal)
    logger.info("Using shared corpus slug: %s", shared_slug)

    _log_lit_review_context(articles_with_reasoning, articles)

    # Build draft prompt with lit review summary as context
    # reference_index.text is the formatted [C*] list (see citations.py);
    # injecting it lets the draft LLM cite sources by key.
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
        meta_review=meta_review,
        run_setup_guidance=state.get("run_setup_guidance"),
        run_focus_guidance=state.get("run_focus_guidance"),
    )

    return prompt


async def _call_draft_agent(
    state: WorkflowState,
    prompt: str,
    openai_tools: list[Any],
    executor: Any,
    count: int,
    max_iterations: int,
) -> str:
    """Invoke the draft agent's tool-calling loop and return its response.

    Args:
        state: Current workflow state.
        prompt: The assembled draft prompt.
        openai_tools: OpenAI-format tool schemas available to the agent.
        executor: Tracked tool executor for the draft phase.
        count: Number of hypotheses being drafted.
        max_iterations: Iteration budget for the tool-calling loop.

    Returns:
        The draft agent's final tool-call-loop response text.
    """
    # Call LLM with tools for drafting
    # scale token budget based on hypotheses count (~200 tokens per hypothesis)
    draft_max_tokens = scaled_max_tokens(
        EXTENDED_MAX_TOKENS,
        count,
        per_item=DRAFT_TOKENS_PER_HYPOTHESIS,
        cap=DRAFT_MAX_TOKENS_CAP,
    )
    logger.info(
        "Calling draft agent: %s iterations, %s max tokens",
        max_iterations,
        draft_max_tokens,
    )

    try:
        final_response, _ = await call_llm_with_tools(
            prompt=prompt,
            model_name=state["model_name"],
            tools=openai_tools,
            tool_executor=executor,
            max_tokens=draft_max_tokens,
            temperature=HIGH_TEMPERATURE,
            max_iterations=max_iterations,
            # Stochastic, diversity-critical generation: keep drafts fresh per
            # run rather than serving a frozen cached draft.
            use_cache=False,
            run_id=state.get("run_id"),
            prompt_name="generate_draft_with_tools",
            prompt_metadata={
                "hypotheses_count": count,
                "max_iterations": max_iterations,
                "prompt_length_chars": len(prompt),
            },
        )
    except Exception as e:
        # No fallback: Phase 1 failing means there are no drafts to pass to
        # Phase 2, so this re-raises rather than degrading gracefully (unlike
        # the enhancement-node fallbacks in llm.py's
        # _ENHANCEMENT_NODE_FALLBACKS).
        logger.error("Draft phase failed: %s", e)
        raise

    return final_response


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
    logger.info(
        "Phase 1: Drafting %s hypotheses by examining literature", count
    )

    # Initialize hybrid tool provider with draft-specific whitelist
    provider, openai_tools, tool_registry = _setup_tool_provider(
        mcp_client, tool_registry, "draft_generation", "draft", logger
    )

    # Calculate dynamic iteration budget based on hypotheses count
    max_iterations = get_draft_max_iterations(count)
    logger.info(
        "Draft budget: %s iterations for %s hypotheses", max_iterations, count
    )

    prompt = _build_draft_prompt(
        state, count, max_iterations, tool_registry, reference_index
    )

    # Track tool calls in draft phase
    draft_tracked_executor, tool_call_counts = provider.tracked_executor(
        "Draft"
    )

    final_response = await _call_draft_agent(
        state,
        prompt,
        openai_tools,
        draft_tracked_executor,
        count,
        max_iterations,
    )

    total_calls = sum(tool_call_counts.values())
    calls_summary = ", ".join(
        f"{name}={count}" for name, count in tool_call_counts.items()
    )
    logger.info(
        "Draft phase complete: %s tool calls (%s)", total_calls, calls_summary
    )

    return _parse_draft_response(final_response)
