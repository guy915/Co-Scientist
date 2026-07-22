"""Stage 1 novelty-analysis helpers for the tool-based validation phase.

Runs the per-draft literature search and fans out per-paper novelty
analyses. The actual per-paper LLM call is threaded in from validate.py as
an ``analyze_paper`` callable so its ``call_llm_json`` seam stays
monkeypatchable on the validate module namespace.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Optional

from co_scientist.agents.generation.literature_tools.validate_search import (
    _search_papers_for_hypothesis,
)
from co_scientist.constants import GENERATE_LIT_TOOL_MAX_PAPERS
from co_scientist.prompts import get_hypothesis_novelty_analysis_prompt
from co_scientist.state import WorkflowState

if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry

logger = logging.getLogger(__name__)

# Type of the per-paper novelty analyzer defined in validate.py
# (_analyze_paper_novelty): (hypothesis_text, hypothesis_idx, paper_id,
# metadata, model_name) -> analysis dict or None on failure.
_PaperAnalyzer = Callable[
    [str, int, str, dict[str, Any], str],
    Awaitable[dict[str, Any] | None],
]


def _build_novelty_analysis_prompt(
    hypothesis_text: str, metadata: dict[str, Any]
) -> str:
    """Build the per-paper novelty-analysis prompt, truncating long fulltext.

    Args:
        hypothesis_text: text of the draft hypothesis being validated.
        metadata: paper metadata dict (title/authors/year/fulltext).

    Returns:
        The assembled novelty-analysis prompt text.
    """
    fulltext = metadata.get("fulltext", "")

    # Truncate if too long. Keeps the per-paper prompt size bounded
    # regardless of how long the source paper's fulltext is.
    max_chars = 200_000
    if len(fulltext) > max_chars:
        fulltext = fulltext[:max_chars] + "\n\n[... truncated for length ...]"

    return get_hypothesis_novelty_analysis_prompt(
        hypothesis_text=hypothesis_text,
        title=metadata.get("title", "Unknown"),
        authors=metadata.get("authors", []),
        year=metadata.get("year"),
        fulltext=fulltext,
    )


async def _gather_novelty_analyses(
    novelty_analysis_tasks: list[Awaitable[dict[str, Any] | None]],
    idx: int,
) -> list[dict[str, Any]]:
    """Await parallel per-paper novelty analyses and drop failed ones.

    Args:
        novelty_analysis_tasks: pending per-paper novelty-analysis
            coroutines for one hypothesis.
        idx: 1-based index of this draft within the batch, for logging.

    Returns:
        List of successful per-paper novelty analysis results.
    """
    logger.info(
        "Running %s novelty analyses in parallel for hypothesis %s",
        len(novelty_analysis_tasks),
        idx,
    )
    novelty_analyses_results = await asyncio.gather(*novelty_analysis_tasks)

    novelty_analyses = [a for a in novelty_analyses_results if a is not None]
    logger.info(
        "Completed %s novelty analyses for hypothesis %s",
        len(novelty_analyses),
        idx,
    )
    return novelty_analyses


async def _run_parallel_novelty_analyses(
    hypothesis_text: str,
    idx: int,
    papers: dict[str, dict[str, Any]],
    model_name: str,
    analyze_paper: _PaperAnalyzer,
) -> list[dict[str, Any]]:
    """Run per-paper novelty analysis for one hypothesis's papers in parallel.

    Args:
        hypothesis_text: text of the draft hypothesis being validated.
        idx: 1-based index of this draft within the batch, for logging.
        papers: papers to analyze, keyed by paper id, in the dict format
            returned by _search_papers_for_hypothesis.
        model_name: model to use for the novelty-analysis LLM calls.
        analyze_paper: per-paper novelty analyzer from validate.py.

    Returns:
        List of successful per-paper novelty analysis results (failed
        analyses are filtered out).
    """
    # Stage 1a: analyze each paper in parallel for this hypothesis
    novelty_analysis_tasks = [
        analyze_paper(hypothesis_text, idx, paper_id, metadata, model_name)
        for paper_id, metadata in papers.items()
    ]

    if not novelty_analysis_tasks:
        logger.warning("No papers with fulltext found for hypothesis %s", idx)
        return []

    return await _gather_novelty_analyses(novelty_analysis_tasks, idx)


async def _search_papers_for_draft(
    hypothesis_text: str,
    idx: int,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    shared_slug: str,
    run_id: str | None,
) -> dict[str, dict[str, Any]]:
    """Search for papers related to one draft, degrading to empty on error.

    Args:
        hypothesis_text: text of the draft hypothesis being validated.
        idx: 1-based index of this draft within the batch, for logging.
        mcp_client: MCP client for tool access.
        tool_registry: optional ToolRegistry for config-driven tool
            selection.
        shared_slug: shared corpus slug reused from the draft phase.
        run_id: current run id, if any.

    Returns:
        Papers in the dict format expected by analyze_paper_novelty, or
        {} if the search failed.
    """
    try:
        papers = await _search_papers_for_hypothesis(
            hypothesis_text=hypothesis_text,
            mcp_client=mcp_client,
            tool_registry=tool_registry,
            max_papers=GENERATE_LIT_TOOL_MAX_PAPERS,
            shared_slug=shared_slug,
            run_id=run_id,
        )
        logger.info("Found %s papers for hypothesis %s", len(papers), idx)
        return papers
    except Exception as e:
        logger.error("Failed to search papers for hypothesis %s: %s", idx, e)
        return {}


async def _gather_hypothesis_novelty_analyses(
    idx: int,
    total: int,
    draft: dict[str, str],
    model_name: str,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    shared_slug: str,
    run_id: str | None,
    analyze_paper: _PaperAnalyzer,
) -> dict[str, Any]:
    """Search literature and run per-paper novelty analysis for one draft.

    Args:
        idx: 1-based index of this draft within the batch, for logging.
        total: total number of drafts being processed, for logging.
        draft: draft dict from Phase 1 (keyed "hypothesis" or "text").
        model_name: model to use for the novelty-analysis LLM calls.
        mcp_client: MCP client for tool access.
        tool_registry: optional ToolRegistry for tool selection.
        shared_slug: shared corpus slug reused from the draft phase.
        run_id: current run id, if any.
        analyze_paper: per-paper novelty analyzer from validate.py.

    Returns:
        Dict with "draft" and "novelty_analyses" keys.
    """
    # Draft dicts key text as either "hypothesis" or "text"; accept both.
    hypothesis_text = draft.get("hypothesis") or draft.get("text", "")
    logger.info(
        "Analyzing hypothesis %s/%s: %s...", idx, total, hypothesis_text[:80]
    )
    papers = await _search_papers_for_draft(
        hypothesis_text, idx, mcp_client, tool_registry, shared_slug, run_id
    )
    novelty_analyses = await _run_parallel_novelty_analyses(
        hypothesis_text, idx, papers, model_name, analyze_paper
    )

    return {"draft": draft, "novelty_analyses": novelty_analyses}


async def _run_novelty_analysis_stage(
    draft_hypotheses: list[dict[str, str]],
    state: WorkflowState,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    shared_slug: str,
    run_id: str | None,
    analyze_paper: _PaperAnalyzer,
) -> list[dict[str, Any]]:
    """Run Stage 1 per-hypothesis novelty analysis for every draft.

    Args:
        draft_hypotheses: list of draft dicts from Phase 1.
        state: current workflow state (used for the novelty-analysis model).
        mcp_client: MCP client for tool access.
        tool_registry: optional ToolRegistry for config-driven tool
            selection.
        shared_slug: shared corpus slug reused from the draft phase.
        run_id: current run id, if any.
        analyze_paper: per-paper novelty analyzer from validate.py.

    Returns:
        List of dicts with "draft" and "novelty_analyses" keys, one per
        draft hypothesis, ready for synthesis.
    """
    total_drafts = len(draft_hypotheses)
    return [
        await _gather_hypothesis_novelty_analyses(
            idx,
            total_drafts,
            draft,
            state["model_name"],
            mcp_client,
            tool_registry,
            shared_slug,
            run_id,
            analyze_paper,
        )
        for idx, draft in enumerate(draft_hypotheses, 1)
    ]
