"""Paper-search helpers for the tool-based validation phase.

Resolves the configured search tool for the "validation" workflow and turns
its responses into the paper-dict format the per-paper novelty analysis
expects. Includes the legacy no-registry fallback that calls
pubmed_search_with_fulltext directly.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, cast

from co_scientist.tools.response_parser import ResponseParser, parse_mcp_result

if TYPE_CHECKING:
    from co_scientist.config import ToolConfig, ToolRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _NoveltySearchContext:
    """Shared inputs for the validation phase's per-hypothesis searches.

    Attributes:
        mcp_client: MCP client for tool access.
        tool_registry: Optional ToolRegistry for config-driven tool
            selection.
        shared_slug: Shared corpus slug reused from the draft phase.
        run_id: Current run id, if any.
    """

    mcp_client: Any
    tool_registry: Optional["ToolRegistry"]
    shared_slug: str
    run_id: str | None


def _find_search_tool(
    tool_registry: Optional["ToolRegistry"],
) -> tuple[str | None, Optional["ToolConfig"]]:
    """Find the first search-category tool from the validation workflow.

    Returns (tool_id, tool_config) or (None, None) if no search tool is
    configured.
    """
    if not tool_registry:
        return None, None

    tool_ids = tool_registry.get_tools_for_workflow("validation")
    # First matching tool wins: workflow config order in the YAML controls
    # priority, this loop just picks the first "search"-category entry.
    for tool_id in tool_ids:
        tool_config = tool_registry.get_tool(tool_id)
        if tool_config and tool_config.category in (
            "search",
            "search_with_content",
        ):
            return tool_id, tool_config
    return None, None


def _first(*values: Any) -> Any:
    """Return the first truthy value, or the last value if none are truthy."""
    for value in values:
        if value:
            return value
    return values[-1] if values else None


def _articles_to_paper_dict(articles: list[Any]) -> dict[str, dict[str, Any]]:
    """Converts parsed Article objects into the paper-dict format.

    The output is the format expected by analyze_paper_novelty.

    Args:
        articles: Article objects parsed from a search tool's response.

    Returns:
        {paper_id: {"title": ..., "authors": [...], "year": ...,
        "fulltext": ...}}
    """
    papers: dict[str, dict[str, Any]] = {}
    for article in articles:
        paper_id = _first(article.source_id, article.url, article.title)
        papers[paper_id] = {
            "title": article.title,
            "authors": article.authors,
            "year": article.year,
            "fulltext": _first(article.content, article.abstract, ""),
        }
    return papers


def _build_search_canonical_params(
    hypothesis_text: str,
    max_papers: int,
    shared_slug: str,
    run_id: str | None,
) -> dict[str, Any]:
    """Build the canonical search params for one hypothesis's paper search.

    Canonical params get mapped by the caller through the tool's own
    parameter mapping (domain/tool-specific field names); "slug" carries
    the shared corpus slug so this search reuses the warm corpus.

    Args:
        hypothesis_text: text of the draft hypothesis being validated.
        max_papers: maximum number of papers to retrieve.
        shared_slug: shared corpus slug reused from the draft phase.
        run_id: current run id, if any.

    Returns:
        The canonical search params dict.
    """
    canonical_params: dict[str, Any] = {
        "query": hypothesis_text[:200],
        "max_papers": max_papers,
        "slug": shared_slug,
    }
    if run_id:
        canonical_params["run_id"] = run_id
    return canonical_params


async def _search_papers_via_tool_config(
    tool_config: "ToolConfig",
    hypothesis_text: str,
    ctx: _NoveltySearchContext,
    max_papers: int,
) -> dict[str, dict[str, Any]]:
    """Search for papers for a hypothesis using a resolved config tool.

    Args:
        tool_config: the resolved search tool config for this workflow.
        hypothesis_text: text of the draft hypothesis being validated.
        ctx: shared search inputs (client, registry, slug, run id).
        max_papers: maximum number of papers to retrieve.

    Returns:
        Papers in the dict format expected by analyze_paper_novelty:
        {paper_id: {"title": ..., "authors": [...], "year": ...,
        "fulltext": ...}}
    """
    canonical_params = _build_search_canonical_params(
        hypothesis_text, max_papers, ctx.shared_slug, ctx.run_id
    )
    mapped_params = tool_config.map_parameters(canonical_params)

    result = await ctx.mcp_client.call_tool(
        tool_config.mcp_tool_name, **mapped_params
    )

    # Parse response through ResponseParser -> List[Article]
    parser = ResponseParser(tool_config)
    articles = parser.parse_to_articles(result)

    return _articles_to_paper_dict(articles)


async def _search_papers_legacy_fallback(
    hypothesis_text: str,
    ctx: _NoveltySearchContext,
    max_papers: int,
) -> dict[str, dict[str, Any]]:
    """Search via the legacy pubmed_search_with_fulltext tool directly.

    Used only when no tool_registry is available at all (backwards
    compatibility for callers that never thread one through state).

    Args:
        hypothesis_text: text of the draft hypothesis being validated.
        ctx: shared search inputs (client, registry, slug, run id).
        max_papers: maximum number of papers to retrieve.

    Returns:
        Papers in the dict format expected by analyze_paper_novelty.
    """
    result = await ctx.mcp_client.call_tool(
        "pubmed_search_with_fulltext",
        query=hypothesis_text[:200],
        max_papers=max_papers,
        slug=ctx.shared_slug,
        run_id=ctx.run_id,
    )
    # Generic fallback normalizer (unlike ResponseParser above, which is
    # driven by the tool's YAML-configured response_format).
    return cast(dict[str, dict[str, Any]], parse_mcp_result(result))


def _skip_search_no_tool_configured() -> dict[str, dict[str, Any]]:
    """Log and return no papers when validation has no search tool configured.

    Not an error: returning {} just means there is nothing to compare this
    hypothesis against, so validation continues without it.

    Returns:
        An empty papers dict.
    """
    logger.warning(
        "no search tools configured for validation workflow,"
        " skipping novelty search"
    )
    return {}


async def _search_papers_for_hypothesis(
    hypothesis_text: str,
    ctx: _NoveltySearchContext,
    max_papers: int,
) -> dict[str, dict[str, Any]]:
    """Search for papers related to a hypothesis using config-driven tools.

    Three-way branch: (1) config-driven search via the resolved tool, (2) a
    registry exists but has no search tool configured for validation --
    skip the novelty search rather than error, (3) legacy no-registry
    fallback calling pubmed_search_with_fulltext directly (backwards
    compatibility).

    Args:
        hypothesis_text: text of the draft hypothesis being validated.
        ctx: shared search inputs (client, registry, slug, run id).
        max_papers: maximum number of papers to retrieve.

    Returns:
        Papers in the dict format expected by analyze_paper_novelty:
        {paper_id: {"title": ..., "authors": [...], "year": ...,
        "fulltext": ...}}
    """
    _, tool_config = _find_search_tool(ctx.tool_registry)

    if tool_config:
        return await _search_papers_via_tool_config(
            tool_config, hypothesis_text, ctx, max_papers
        )

    if ctx.tool_registry:
        return _skip_search_no_tool_configured()

    return await _search_papers_legacy_fallback(
        hypothesis_text, ctx, max_papers
    )
