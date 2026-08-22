"""Phase 1: Draft hypotheses by reading papers and identifying gaps.

This is the first phase of tool-based generation. The agent reads pre-curated
papers using tools and drafts initial hypothesis ideas based on identified gaps.

The helpers live in sibling modules (draft_tools.py for tool-provider setup,
draft_prompt.py for prompt assembly); the call_llm_with_tools LLM seam is
called from this module so tests can monkeypatch it on this namespace. All
helper names are re-exported here for compatibility.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from co_scientist.agents.generation.literature_tools.draft_prompt import (
    _DraftStateContext as _DraftStateContext,
)
from co_scientist.agents.generation.literature_tools.draft_prompt import (
    _gather_draft_state_context as _gather_draft_state_context,
)
from co_scientist.agents.generation.literature_tools.draft_prompt import (
    _invoke_draft_prompt_builder as _invoke_draft_prompt_builder,
)
from co_scientist.agents.generation.literature_tools.draft_prompt import (
    _log_lit_review_context as _log_lit_review_context,
)
from co_scientist.agents.generation.literature_tools.draft_skills import (
    DraftSkills,
    attach_skills,
)
from co_scientist.agents.generation.literature_tools.draft_tools import (
    _resolve_mcp_whitelist as _resolve_mcp_whitelist,
)
from co_scientist.agents.generation.literature_tools.draft_tools import (
    _resolve_tool_registry_fallback as _resolve_tool_registry_fallback,
)
from co_scientist.agents.generation.literature_tools.draft_tools import (
    _setup_tool_provider as _setup_tool_provider,
)
from co_scientist.agents.generation.research_expansion import (
    EXPANSION_EXTRA_DRAFT_ITERATIONS,
    is_research_expansion,
)
from co_scientist.constants import (
    DEEP_HYPOTHESIS_MAX_TOKENS,
    DRAFT_MAX_TOKENS_CAP,
    DRAFT_TOKENS_PER_HYPOTHESIS,
    HIGH_TEMPERATURE,
    get_draft_max_iterations,
    scaled_max_tokens,
)
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    ToolLoop,
    call_llm_with_tools,
)
from co_scientist.llm_json import parse_tool_loop_json
from co_scientist.state import WorkflowState

if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _DraftCall:
    """Inputs for one draft-phase tool-calling LLM invocation.

    Attributes:
        prompt: The assembled draft prompt.
        openai_tools: OpenAI-format tool schemas available to the agent.
        executor: Tracked tool executor for the draft phase.
        count: Number of hypotheses being drafted.
        max_iterations: Iteration budget for the tool-calling loop.
    """

    prompt: str
    openai_tools: list[Any]
    executor: Any
    count: int
    max_iterations: int


def _parse_draft_response(final_response: str) -> list[dict[str, str]]:
    """Parse the draft agent's final response into draft hypothesis dicts.

    Args:
        final_response: the draft agent's final tool-call-loop response.

    Returns:
        List of draft dicts with text, gap_reasoning, literature_sources.

    Raises:
        ResponseParseError: if the response cannot be parsed as JSON even
            after repair attempts. Failing hard here is deliberate: an empty
            Phase 1 would make Phase 2 a silent no-op too.
    """
    drafts: list[dict[str, str]] = parse_tool_loop_json(
        final_response, "drafts", "Draft phase"
    )
    logger.info("Parsed %s draft hypotheses", len(drafts))
    return drafts


def _compute_draft_max_tokens(count: int, max_iterations: int) -> int:
    """Scale and log the draft agent's max-token budget for this call.

    Args:
        count: Number of hypotheses being drafted.
        max_iterations: Iteration budget for the tool-calling loop.

    Returns:
        The scaled max-tokens budget for the draft agent call.
    """
    # Scale the token budget with the hypotheses count (~200 tokens per
    # hypothesis). K6: the base is the deep-generation budget because the
    # draft prompt now requires full-depth ideas (a shallow draft becomes
    # a shallow final hypothesis).
    draft_max_tokens = scaled_max_tokens(
        DEEP_HYPOTHESIS_MAX_TOKENS,
        count,
        per_item=DRAFT_TOKENS_PER_HYPOTHESIS,
        cap=DRAFT_MAX_TOKENS_CAP,
    )
    logger.info(
        "Calling draft agent: %s iterations, %s max tokens",
        max_iterations,
        draft_max_tokens,
    )
    return draft_max_tokens


def _build_draft_prompt_metadata(
    count: int, max_iterations: int, prompt: str
) -> dict[str, Any]:
    """Build the prompt_metadata dict logged with a draft LLM call.

    Args:
        count: Number of hypotheses being drafted.
        max_iterations: Iteration budget for the tool-calling loop.
        prompt: The assembled draft prompt.

    Returns:
        The prompt_metadata dict for call_llm_with_tools.
    """
    return {
        "hypotheses_count": count,
        "max_iterations": max_iterations,
        "prompt_length_chars": len(prompt),
    }


def _count_assistant_turns(messages: list[dict[str, Any]]) -> int:
    """Count real completions spent in a tool-call loop's message history.

    Each tool-loop iteration issues exactly one ``litellm.acompletion`` and
    appends its assistant message to the running conversation
    (``llm_tool_loop.py``), so the assistant-role entries are a precise
    count of real LLM calls the loop made -- finding L3's fix for
    tool-based generation, without needing to instrument ``llm.py`` itself.

    Args:
        messages: The full running conversation returned by
            ``call_llm_with_tools``.

    Returns:
        The number of assistant-role turns, i.e. real completions made.
    """
    return sum(1 for m in messages if m.get("role") == "assistant")


async def _call_draft_llm_with_tools(
    state: WorkflowState,
    call: _DraftCall,
    draft_max_tokens: int,
) -> tuple[str, int]:
    """Call the tool-calling draft LLM once and return its final response.

    Args:
        state: Current workflow state.
        call: Inputs for this draft-phase LLM invocation.
        draft_max_tokens: Token budget for this call.

    Returns:
        Tuple of (final response text, real LLM calls made by the loop).
    """
    # Diversity-critical generation: keep drafts fresh, never cache-frozen.
    final_response, messages = await call_llm_with_tools(
        prompt=call.prompt,
        spec=CompletionSpec(
            model_name=state["model_name"],
            max_tokens=draft_max_tokens,
            temperature=HIGH_TEMPERATURE,
        ),
        loop=ToolLoop(
            tools=call.openai_tools,
            executor=call.executor,
            max_iterations=call.max_iterations,
        ),
        options=LLMCallOptions(
            use_cache=False,
            run_id=state.get("run_id"),
            prompt_name="generate_draft_with_tools",
            prompt_metadata=_build_draft_prompt_metadata(
                call.count, call.max_iterations, call.prompt
            ),
        ),
    )
    return final_response, _count_assistant_turns(messages)


async def _invoke_draft_llm(
    state: WorkflowState,
    call: _DraftCall,
    draft_max_tokens: int,
) -> tuple[str, int]:
    """Run the draft agent's tool-calling LLM call, re-raising on failure.

    Args:
        state: Current workflow state.
        call: Inputs for this draft-phase LLM invocation.
        draft_max_tokens: Token budget for this call.

    Returns:
        Tuple of (final response text, real LLM calls made).
    """
    try:
        return await _call_draft_llm_with_tools(state, call, draft_max_tokens)
    except Exception as e:
        # No fallback: Phase 1 failing means there are no drafts to pass to
        # Phase 2, so this re-raises rather than degrading gracefully (unlike
        # the enhancement-node fallbacks in llm.py's
        # _ENHANCEMENT_NODE_FALLBACKS).
        logger.error("Draft phase failed: %s", e)
        raise


async def _call_draft_agent(
    state: WorkflowState,
    call: _DraftCall,
) -> tuple[str, int]:
    """Invoke the draft agent's tool-calling loop and return its response.

    Args:
        state: Current workflow state.
        call: Inputs for this draft-phase LLM invocation.

    Returns:
        Tuple of (final response text, real LLM calls made).
    """
    draft_max_tokens = _compute_draft_max_tokens(
        call.count, call.max_iterations
    )
    return await _invoke_draft_llm(state, call, draft_max_tokens)


def _log_draft_completion(tool_call_counts: dict[str, int]) -> None:
    """Log the total/per-tool call counts for the completed draft phase.

    Args:
        tool_call_counts: per-tool-name call counts from the tracked
            executor.
    """
    total_calls = sum(tool_call_counts.values())
    calls_summary = ", ".join(
        f"{name}={count}" for name, count in tool_call_counts.items()
    )
    logger.info(
        "Draft phase complete: %s tool calls (%s)", total_calls, calls_summary
    )


def _compute_draft_iteration_budget(
    count: int, is_expansion: bool = False
) -> int:
    """Scale and log the draft phase's iteration budget for this call.

    Args:
        count: Number of hypotheses being drafted.
        is_expansion: Whether this draft is a research-expansion cycle
            (E11b); broad exploratory retrieval gets extra round-trips.

    Returns:
        The iteration budget for the draft tool-calling loop.
    """
    # Calculate dynamic iteration budget based on hypotheses count
    max_iterations = get_draft_max_iterations(count)
    if is_expansion:
        max_iterations += EXPANSION_EXTRA_DRAFT_ITERATIONS
    logger.info(
        "Draft budget: %s iterations for %s hypotheses%s",
        max_iterations,
        count,
        " (research expansion)" if is_expansion else "",
    )
    return max_iterations


def _prepare_draft_call(
    state: WorkflowState,
    count: int,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    reference_index: Any | None,
) -> tuple[DraftSkills, int, str]:
    """Resolve tools and assemble the prompt for one draft-phase call.

    Args:
        state: Current workflow state.
        count: Number of hypotheses to draft.
        mcp_client: MCP client for tool access.
        tool_registry: Optional ToolRegistry for config-driven tool
            selection.
        reference_index: Optional citation reference index supplying the
            `[C*]` reference list.

    Returns:
        Tuple of (the surface to run against, max_iterations, prompt).
    """
    # Initialize hybrid tool provider with draft-specific whitelist
    provider, openai_tools, tool_registry = _setup_tool_provider(
        mcp_client, tool_registry, "draft_generation", "draft", logger
    )

    # Adds the science skills where they are installed, and returns the
    # arguments untouched where they are not.
    skills = attach_skills(state, provider, openai_tools)

    max_iterations = (
        _compute_draft_iteration_budget(
            count, is_expansion=is_research_expansion(state)
        )
        + skills.extra_iterations
    )

    prompt = _invoke_draft_prompt_builder(
        count,
        max_iterations,
        tool_registry,
        reference_index,
        _gather_draft_state_context(state, skills.section),
    )

    return skills, max_iterations, prompt


async def _run_draft_pipeline(
    state: WorkflowState,
    count: int,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    reference_index: Any | None,
) -> tuple[str, dict[str, int], int]:
    """Set up tools, build the prompt, and run the draft agent's tool loop.

    Args:
        state: Current workflow state.
        count: Number of hypotheses to draft.
        mcp_client: MCP client for tool access.
        tool_registry: Optional ToolRegistry for config-driven tool
            selection.
        reference_index: Optional citation reference index supplying the
            `[C*]` reference list.

    Returns:
        Tuple of (draft agent's final response text, per-tool call counts,
        real LLM calls made).
    """
    skills, max_iterations, prompt = _prepare_draft_call(
        state, count, mcp_client, tool_registry, reference_index
    )

    # Track tool calls in draft phase
    draft_tracked_executor, tool_call_counts = skills.provider.tracked_executor(
        "Draft"
    )

    final_response, llm_calls = await _call_draft_agent(
        state,
        _DraftCall(
            prompt=prompt,
            openai_tools=skills.tools,
            executor=draft_tracked_executor,
            count=count,
            max_iterations=max_iterations,
        ),
    )

    return final_response, tool_call_counts, llm_calls


async def draft_hypotheses(
    state: WorkflowState,
    count: int,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"] = None,
    reference_index: Any | None = None,
) -> tuple[list[dict[str, str]], int]:
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
        Tuple of (draft dicts with text/gap_reasoning/literature_sources,
        real LLM calls made -- finding L3).
    """
    logger.info(
        "Phase 1: Drafting %s hypotheses by examining literature", count
    )

    final_response, tool_call_counts, llm_calls = await _run_draft_pipeline(
        state, count, mcp_client, tool_registry, reference_index
    )

    _log_draft_completion(tool_call_counts)

    return _parse_draft_response(final_response), llm_calls
