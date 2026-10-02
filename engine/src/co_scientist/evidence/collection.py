"""Collect evidence across sources, preserving budgets and provenance."""

from typing import Any

from co_scientist.constants import corpus_slug
from co_scientist.evidence.search import (
    _phase2_collect_papers_multi_source,
    _phase2_collect_papers_single_source,
    _SearchRunContext,
)
from co_scientist.evidence.search_support import SearchConfig
from co_scientist.mcp_client import MCPToolClient
from co_scientist.state import WorkflowState


async def collect_papers(
    queries: list[str],
    state: WorkflowState,
    config: SearchConfig,
    mcp_client: MCPToolClient,
    search_errors: list[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Phase 2: collect papers from configured sources.

    Dispatches to the multi-source or single-source collection path based on
    config.is_multi_source. The slug ties this run's searches to the shared
    on-disk corpus so a warm-started corpus from a prior run/tool-based
    generation phase is reused rather than re-downloaded.
    """
    ctx = _SearchRunContext(
        slug=corpus_slug(state["research_goal"]),
        run_id=state["run_id"],
        mcp_client=mcp_client,
        errors=search_errors,
    )

    if config.is_multi_source:
        return await _phase2_collect_papers_multi_source(queries, config, ctx)
    return await _phase2_collect_papers_single_source(queries, config, ctx)
