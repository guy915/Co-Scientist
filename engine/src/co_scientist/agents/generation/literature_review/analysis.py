"""Phase 3: literature review paper analysis.

Analyzes each paper with usable content (fulltext, or abstract as fallback)
for gaps and opportunities relative to the research goal, running one LLM call
per paper in parallel.
"""

import asyncio
import logging
from typing import Any

from co_scientist.constants import (
    DEFAULT_MAX_TOKENS,
    HIGH_TEMPERATURE,
)
from co_scientist.evidence.helpers import (
    get_paper_content_for_analysis,
    get_papers_with_content,
    parse_year_from_metadata,
)
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.llm import (
    CompletionSpec,
    call_llm_json,
)
from co_scientist.prompts import get_literature_review_paper_analysis_prompt
from co_scientist.schemas import LITERATURE_PAPER_ANALYSIS_SCHEMA
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


async def _run_paper_analysis_llm(
    paper_id: str,
    metadata: dict[str, Any],
    research_goal: str,
    model_name: str,
) -> dict[str, Any]:
    """Builds the paper-analysis prompt and calls the LLM, unwrapped."""
    year = parse_year_from_metadata(metadata)
    # Prefers fulltext, falls back to abstract, and truncates to a
    # bounded length so a single very long paper cannot blow the
    # analysis prompt's token budget.
    content = get_paper_content_for_analysis(metadata)

    prompt = get_literature_review_paper_analysis_prompt(
        research_goal=research_goal,
        title=metadata.get("title", "Unknown"),
        authors=metadata.get("authors", []),
        year=year,
        fulltext=content,
    )

    analysis = await call_llm_json(
        prompt=prompt,
        spec=CompletionSpec(
            model_name=model_name,
            max_tokens=DEFAULT_MAX_TOKENS,
            temperature=HIGH_TEMPERATURE,
            json_schema=LITERATURE_PAPER_ANALYSIS_SCHEMA,
        ),
    )

    logger.debug(
        "Analyzed paper %s: %s",
        paper_id,
        metadata.get("title", "Unknown")[:60],
    )
    return {
        "paper_id": paper_id,
        "metadata": metadata,
        "analysis": analysis,
    }


async def _analyze_single_paper(
    paper_id: str,
    metadata: dict[str, Any],
    research_goal: str,
    model_name: str,
) -> dict[str, Any] | None:
    """Analyze a single paper for gaps and opportunities."""
    try:
        return await _run_paper_analysis_llm(
            paper_id, metadata, research_goal, model_name
        )
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception as e:
        # Returning None (not raising) lets _phase3_analyze_papers filter
        # this paper out and continue synthesizing from the rest.
        logger.error("Failed to analyze paper %s: %s", paper_id, e)
        return None


def _log_sample_analysis(analyses: list[dict[str, Any]]) -> None:
    """Debug-log the analysis keys of the first paper, if any were analyzed."""
    if not analyses:
        return
    first = analyses[0]
    logger.debug(
        "Sample analysis structure - keys: %s",
        list(first.get("analysis", {}).keys()),
    )


async def _phase3_analyze_papers(
    all_paper_metadata: dict[str, dict[str, Any]],
    state: WorkflowState,
) -> list[dict[str, Any]]:
    """Phase 3: Analyze papers with content for gaps and opportunities."""
    # Papers with fulltext or a source-provided abstract are eligible; records
    # with metadata alone are excluded rather than counted as analyzed.
    papers_with_content = get_papers_with_content(all_paper_metadata)

    if not papers_with_content:
        logger.error("No papers have content for analysis")
        return []

    logger.info(
        "Phase 3: analyzing %s papers (parallel)", len(papers_with_content)
    )

    # One LLM call per paper, all in parallel.
    tasks = [
        _analyze_single_paper(
            paper_id,
            metadata,
            state["research_goal"],
            state["model_name"],
        )
        for paper_id, metadata in papers_with_content.items()
    ]
    results = await asyncio.gather(*tasks)

    # Filter out failed analyses
    analyses = [r for r in results if r is not None]
    logger.info(
        "Completed %s/%s paper analyses",
        len(analyses),
        len(papers_with_content),
    )

    _log_sample_analysis(analyses)

    return analyses
