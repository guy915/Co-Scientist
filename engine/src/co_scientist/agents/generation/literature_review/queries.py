"""Phase 1: literature review query generation.

Generates the search queries used by Phase 2, preferring an MCP query-
generation tool when one is configured and falling back to a source-aware LLM
prompt (and finally to the raw research goal).
"""

import logging
from typing import TYPE_CHECKING, cast

from co_scientist.agents.generation.literature_review.helpers import (
    SearchConfig,
    determine_query_source_type,
    parse_mcp_query_result,
)
from co_scientist.agents.generation.literature_review.outcomes import (
    _describe_exc,
)
from co_scientist.constants import (
    DEFAULT_MAX_TOKENS,
    HIGH_TEMPERATURE,
)
from co_scientist.llm import (
    CompletionSpec,
    call_llm_json,
)
from co_scientist.mcp_client import MCPToolClient
from co_scientist.prompts import (
    LiteratureQueryInputs,
    get_literature_review_query_generation_prompt,
)
from co_scientist.schemas import LITERATURE_QUERY_SCHEMA
from co_scientist.state import WorkflowState

if TYPE_CHECKING:
    from co_scientist.config import WorkflowConfig

logger = logging.getLogger(__name__)


async def _generate_queries_via_mcp(
    mcp_client: MCPToolClient,
    research_goal: str,
    tool_name: str,
    query_format: str,
) -> list[str]:
    """Generate queries using MCP tool."""
    try:
        result = await mcp_client.call_tool(
            tool_name,
            research_goal=research_goal,
            query_format=query_format,
        )
        queries = parse_mcp_query_result(result)
        logger.info("MCP query generation returned %s queries", len(queries))
        return queries
    except Exception as e:
        # An empty list here (rather than raising) is the signal that lets
        # _phase1_generate_queries fall through to the LLM-based generator.
        logger.warning(
            "MCP query generation failed: %s, falling back to LLM",
            _describe_exc(e),
        )
        return []


async def _generate_queries_via_llm(
    state: WorkflowState,
    config: SearchConfig,
) -> list[str]:
    """Generate queries using LLM with source-aware prompt."""
    # source_type steers the prompt wording (e.g. "academic" boolean search
    # phrasing vs "knowledge_graph" entity-oriented phrasing) so the LLM
    # produces queries that suit whatever source(s) are actually configured.
    source_type = determine_query_source_type(
        config.workflow,
        config.tool_registry,
        config.search_tool_config,
        config.is_multi_source,
    )
    logger.debug("Using %s query generation prompt", source_type)

    prompt = get_literature_review_query_generation_prompt(
        research_goal=state["research_goal"],
        source_type=source_type,
        inputs=LiteratureQueryInputs(
            preferences=state.get("preferences", ""),
            attributes=state.get("attributes", []),
            user_literature=state.get("literature", []),
            user_hypotheses=state.get("starting_hypotheses", []),
        ),
    )

    try:
        result = await call_llm_json(
            prompt=prompt,
            spec=CompletionSpec(
                model_name=state["model_name"],
                max_tokens=DEFAULT_MAX_TOKENS,
                temperature=HIGH_TEMPERATURE,
                json_schema=LITERATURE_QUERY_SCHEMA,
            ),
        )
        return cast(list[str], result.get("queries", []))
    except Exception as e:
        logger.warning("LLM query generation failed: %s", e)
        return []


def _resolve_query_format(workflow: "WorkflowConfig") -> str:
    """Resolve the configured query format, defaulting to "boolean"."""
    return workflow.query_format or "boolean"


def _resolve_query_generation_tool(
    config: SearchConfig,
) -> tuple[str, str] | None:
    """Resolve the configured MCP query-generation (tool_name, query_format).

    Returns None when no query_generation_tool is configured (or its tool
    config can't be resolved), which signals the caller to fall through to
    LLM-based generation.
    """
    if not (
        config.tool_registry
        and config.workflow
        and config.workflow.query_generation_tool
    ):
        return None

    tool_cfg = config.tool_registry.get_tool(
        config.workflow.query_generation_tool
    )
    if not tool_cfg:
        return None

    return tool_cfg.mcp_tool_name, _resolve_query_format(config.workflow)


async def _try_mcp_query_generation(
    state: WorkflowState,
    config: SearchConfig,
    mcp_client: MCPToolClient,
) -> list[str]:
    """Generate queries via the configured MCP query-generation tool, if any.

    Returns an empty list when no query_generation_tool is configured (or
    its tool config can't be resolved), which signals the caller to fall
    through to LLM-based generation.
    """
    resolved = _resolve_query_generation_tool(config)
    if not resolved:
        return []

    tool_name, query_format = resolved
    logger.info(
        "Using MCP query generation: %s (format: %s)", tool_name, query_format
    )
    return await _generate_queries_via_mcp(
        mcp_client,
        state["research_goal"],
        tool_name,
        query_format,
    )


async def _phase1_generate_queries(
    state: WorkflowState,
    config: SearchConfig,
    mcp_client: MCPToolClient,
) -> list[str]:
    """Phase 1: Generate search queries."""
    logger.info("Phase 1: generating search queries")

    queries = await _try_mcp_query_generation(state, config, mcp_client)

    # Fallback to LLM-based generation
    # Also the primary path when no query_generation_tool is configured at
    # all.
    if not queries:
        queries = await _generate_queries_via_llm(state, config)

    # Final fallback to research goal
    # Guarantees Phase 2 always has at least one query to search with, even
    # if both generators failed.
    if not queries:
        logger.warning("No queries generated, using research goal")
        queries = [state["research_goal"]]

    # Limit to 3 queries max
    # Bounds the number of parallel search calls (and downstream
    # papers-per-query fan-out) regardless of how many queries either
    # generator returned.
    queries = queries[:3]

    logger.info("Generated %s search queries", len(queries))
    for i, q in enumerate(queries, 1):
        logger.debug("Query %s: %s", i, q)

    return queries
