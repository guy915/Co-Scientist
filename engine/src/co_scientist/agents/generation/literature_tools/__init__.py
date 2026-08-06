"""Tool-based literature generation - two-phase approach.

Phase 1 (draft.py): Read papers and draft hypotheses
Phase 2 (validate.py): Search literature and validate/refine novelty

Orchestrates both phases to generate hypotheses with dynamic literature access.
"""

import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from co_scientist.agents.generation.citations import (
        ReferenceIndex,
    )

from co_scientist.agents.generation.literature_tools.draft import (
    draft_hypotheses,
)
from co_scientist.agents.generation.literature_tools.validate import (
    validate_hypotheses,
)
from co_scientist.mcp_client import get_mcp_client
from co_scientist.models import Hypothesis
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


def _count_used_articles(articles: list[Any]) -> int:
    """Count articles literature review actually read (used_in_analysis)."""
    return sum(1 for art in articles if art.used_in_analysis)


def _count_used_articles_with_pdfs(articles: list[Any]) -> int:
    """Count analyzed articles that also carry full-text PDF links."""
    return sum(1 for art in articles if art.used_in_analysis and art.pdf_links)


def _log_warm_start_diagnostics(articles: list[Any] | None) -> None:
    """Log how much lit-review context is already warm-started for drafting.

    Diagnostic-only: reports how much literature-review context is already
    warm-started before drafting begins vs. how much the draft agent will
    need to search for itself. Does not affect control flow.

    Args:
        articles: articles from state.articles (may be empty or None).
    """
    if not articles:
        return

    # used_in_analysis marks articles literature review actually read (vs.
    # merely fetched), the real warm-start signal for drafting.
    used_count = _count_used_articles(articles)
    logger.debug(
        "state.articles contains %s total articles,"
        " %s with used_in_analysis=True",
        len(articles),
        used_count,
    )
    if used_count > 0:
        # Split further for logging only: PDF-backed articles carry full
        # text into the draft prompt; abstract-only ones carry less.
        articles_with_pdfs = _count_used_articles_with_pdfs(articles)
        logger.info(
            "Including %s analyzed articles in prompt"
            " (%s with PDFs, %s abstract-only)",
            used_count,
            articles_with_pdfs,
            used_count - articles_with_pdfs,
        )
    else:
        # No warm-started reading context available; Phase 1 falls back to
        # discovering and reading literature via its own tool calls.
        logger.warning(
            "No articles with used_in_analysis=True found in state"
            " - agent will search fresh"
        )


async def _get_mcp_client_for_generation(
    tool_registry: Any | None,
) -> Any:
    """Fetches the MCP client used by both generation phases.

    Without an MCP client neither phase can read or search literature, so
    failures are logged and re-raised rather than degraded.

    Args:
        tool_registry: optional ToolRegistry for config-driven tool
            selection.

    Returns:
        The MCP client.
    """
    try:
        return await get_mcp_client(tool_registry=tool_registry)
    except Exception as e:
        logger.warning("Failed to get MCP client: %s", e)
        raise


def _log_generated_hypothesis_methods(hypotheses: list[Hypothesis]) -> None:
    """Debug-trace the final generation_method/text for each hypothesis.

    Args:
        hypotheses: hypotheses produced by the two-phase pipeline.
    """
    for i, hyp in enumerate(hypotheses):
        method = hyp.generation_method
        logger.debug(
            "tool-generated hypothesis %s: generation_method=%s, text=%s...",
            i + 1,
            method.value if method else None,
            hyp.text[:80],
        )


async def _run_draft_phase(
    state: WorkflowState,
    count: int,
    mcp_client: Any,
    tool_registry: Any | None,
    reference_index: Optional["ReferenceIndex"],
) -> tuple[list[dict[str, str]], int]:
    """Run Phase 1: draft hypotheses from identified literature gaps.

    Args:
        state: Current workflow state.
        count: Number of hypotheses to draft.
        mcp_client: MCP client for tool access.
        tool_registry: optional ToolRegistry for config-driven tool
            selection.
        reference_index: Citation key -> source mapping for structured
            citations.

    Returns:
        Tuple of (draft dicts from Phase 1, real LLM calls made).
    """
    draft_hyps, llm_calls = await draft_hypotheses(
        state=state,
        count=count,
        mcp_client=mcp_client,
        tool_registry=tool_registry,
        reference_index=reference_index,
    )
    logger.info("Phase 1 complete: drafted %s hypotheses", len(draft_hyps))
    return draft_hyps, llm_calls


async def _run_validate_phase(
    state: WorkflowState,
    draft_hyps: list[dict[str, str]],
    mcp_client: Any,
    tool_registry: Any | None,
    reference_index: Optional["ReferenceIndex"],
) -> tuple[list[Hypothesis], int]:
    """Run Phase 2: search competing work and decide approve/refine/pivot.

    Output is tagged GenerationMethod.LITERATURE_TOOLS inside
    hypothesis_from_llm_output (citations.py), which validate_hypotheses
    calls per hypothesis.

    Args:
        state: Current workflow state.
        draft_hyps: draft dicts produced by Phase 1.
        mcp_client: MCP client for tool access.
        tool_registry: optional ToolRegistry for config-driven tool
            selection.
        reference_index: Citation key -> source mapping for structured
            citations.

    Returns:
        Tuple of (validated hypotheses tagged
        GenerationMethod.LITERATURE_TOOLS, real LLM calls made).
    """
    hypotheses, llm_calls = await validate_hypotheses(
        state=state,
        draft_hypotheses=draft_hyps,
        mcp_client=mcp_client,
        tool_registry=tool_registry,
        reference_index=reference_index,
    )
    logger.info("Phase 2 complete: validated %s hypotheses", len(hypotheses))
    return hypotheses, llm_calls


async def generate_with_tools(
    state: WorkflowState,
    count: int,
    reference_index: Optional["ReferenceIndex"] = None,
) -> tuple[list[Hypothesis], int]:
    """Generates hypotheses with a two-phase tool-based process.

    Phase 1: draft hypotheses by reading papers and identifying gaps
    Phase 2: validate novelty by searching and refining/pivoting

    Args:
        state: Current workflow state
        count: Number of hypotheses to generate
        reference_index: Citation key → source mapping for structured citations

    Returns:
        Tuple of (validated hypotheses with
        generation_method="literature_tools", real LLM calls made across
        both phases -- finding L3, this path previously reported none).
    """
    logger.info(
        "Generating %s hypotheses with two-phase tool-based process", count
    )

    # Resolved once and threaded into both phases below, so both resolve
    # tool whitelists from the same registry (see draft.py/validate.py).
    tool_registry = state.get("tool_registry")
    mcp_client = await _get_mcp_client_for_generation(tool_registry)

    _log_warm_start_diagnostics(state.get("articles", []))

    draft_hyps, draft_calls = await _run_draft_phase(
        state, count, mcp_client, tool_registry, reference_index
    )

    hypotheses, validate_calls = await _run_validate_phase(
        state, draft_hyps, mcp_client, tool_registry, reference_index
    )

    _log_generated_hypothesis_methods(hypotheses)

    return hypotheses, draft_calls + validate_calls


__all__ = ["draft_hypotheses", "generate_with_tools", "validate_hypotheses"]
