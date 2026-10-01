"""Phase 1: literature review query generation.

Generates the search queries used by Phase 2, preferring an MCP query-
generation tool when one is configured and falling back to a source-aware LLM
prompt (and finally to a keyword-distilled form of the research goal).
"""

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from co_scientist.constants import (
    DEFAULT_MAX_TOKENS,
    HIGH_TEMPERATURE,
    LITERATURE_REVIEW_MAX_QUERIES,
)
from co_scientist.evidence.errors import (
    describe_exception,
)
from co_scientist.evidence.helpers import (
    SearchConfig,
    determine_query_source_type,
    parse_mcp_query_result,
)
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
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
            describe_exception(e),
        )
        return []


def _build_query_generation_prompt(
    state: WorkflowState,
    config: SearchConfig,
) -> str:
    """Build the source-aware query-generation prompt.

    source_type steers the prompt wording (e.g. "academic" boolean search
    phrasing vs "knowledge_graph" entity-oriented phrasing) so the LLM
    produces queries that suit whatever source(s) are actually configured.
    """
    source_type = determine_query_source_type(
        config.workflow,
        config.tool_registry,
        config.search_tool_config,
        config.is_multi_source,
    )
    logger.debug("Using %s query generation prompt", source_type)
    return get_literature_review_query_generation_prompt(
        research_goal=state["research_goal"],
        source_type=source_type,
        inputs=LiteratureQueryInputs(
            preferences=state.get("preferences", ""),
            attributes=state.get("attributes", []),
            user_literature=state.get("literature", []),
            user_hypotheses=state.get("starting_hypotheses", []),
        ),
        # Audit E7: search what the meta-review says is missing or weak.
        # Empty on iteration 1, when no critique exists yet.
        meta_review=state.get("meta_review"),
    )


async def _generate_queries_via_llm(
    state: WorkflowState,
    config: SearchConfig,
) -> list[str]:
    """Generate queries using LLM with source-aware prompt."""
    prompt = _build_query_generation_prompt(state, config)
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
    except TASK_CONTROL_FLOW_ERRORS:
        raise
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


# Words too generic to help narrow a literature search; stripping them off
# the research goal keeps the final fallback keyword-shaped instead of a
# prose sentence, matching the "3-8 key terms" queries the query-generation
# prompt asks the model for on every other path.
_GOAL_FALLBACK_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "for",
        "in",
        "on",
        "to",
        "and",
        "or",
        "not",
        "is",
        "are",
        "how",
        "does",
        "do",
        "what",
        "why",
        "can",
        "could",
        "will",
        "would",
        "that",
        "this",
        "these",
        "those",
        "by",
        "as",
        "be",
        "using",
        "use",
        "via",
        "into",
        "from",
        "about",
        "we",
        "our",
        "with",
    }
)

# Mirrors the "3-8 key terms" guidance the query-generation prompt gives the
# model, so the fallback reads the same as a normally-generated query.
_GOAL_FALLBACK_MAX_TERMS = 8


def _distill_goal_to_query(research_goal: str) -> str:
    """Reduce a prose research goal to a keyword-shaped fallback query.

    Only reached once both query generators have already failed, so this is
    the literal text a downstream source's ``esearch`` sees. A full prose
    sentence -- articles, punctuation, question words and all -- collapses
    under PubMed's AND-every-term semantics before the broadening ladder
    even gets a chance to run, so this strips common stopwords and caps the
    term count instead of forwarding the goal verbatim.

    Args:
        research_goal: The run's research goal, as free text.

    Returns:
        A space-joined keyword string, or the original goal unchanged if
        stripping stopwords would leave nothing to search with.
    """
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9-]*", research_goal)
    keywords = [w for w in words if w.lower() not in _GOAL_FALLBACK_STOPWORDS]
    if not keywords:
        return research_goal
    return " ".join(keywords[:_GOAL_FALLBACK_MAX_TERMS])


@dataclass(frozen=True)
class QueryPhaseResult:
    """Phase 1 output: the resolved search queries plus real LLM calls spent.

    Bundled together (rather than two loose return values) so downstream
    callers stay under the five-parameter limit once they also need to
    thread the call count alongside the queries.

    Attributes:
        queries: Generated (MCP-tool, LLM, or keyword-distilled) queries.
        llm_calls: Real LLM calls Phase 1 spent generating them.
    """

    queries: list[str]
    llm_calls: int


async def _phase1_generate_queries(
    state: WorkflowState,
    config: SearchConfig,
    mcp_client: MCPToolClient,
) -> QueryPhaseResult:
    """Phase 1: Generate search queries.

    Returns:
        The resolved queries paired with real LLM calls spent. The
        MCP-tool and keyword-distillation paths make no LLM call; only the
        LLM-fallback generator does, so llm_calls is 1 exactly when that
        path ran (finding L3 -- literature review previously reported no
        llm_calls at all).
    """
    logger.info("Phase 1: generating search queries")

    queries = await _try_mcp_query_generation(state, config, mcp_client)

    # Fallback to LLM-based generation
    # Also the primary path when no query_generation_tool is configured at
    # all.
    llm_calls = 0
    if not queries:
        queries = await _generate_queries_via_llm(state, config)
        llm_calls = 1

    # Final fallback to a keyword-distilled research goal
    # Guarantees Phase 2 always has at least one query to search with, even
    # if both generators failed.
    if not queries:
        fallback = _distill_goal_to_query(state["research_goal"])
        logger.warning(
            "No queries generated, falling back to distilled goal: %s",
            fallback,
        )
        queries = [fallback]

    # Bounds the number of parallel search calls (and downstream
    # papers-per-query fan-out) regardless of how many queries either
    # generator returned.
    queries = queries[:LITERATURE_REVIEW_MAX_QUERIES]

    logger.info("Generated %s search queries", len(queries))
    for i, q in enumerate(queries, 1):
        logger.debug("Query %s: %s", i, q)

    return QueryPhaseResult(queries=queries, llm_calls=llm_calls)
