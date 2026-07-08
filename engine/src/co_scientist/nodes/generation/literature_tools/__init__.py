"""Tool-based literature generation - two-phase approach.

Phase 1 (draft.py): Read papers and draft hypotheses
Phase 2 (validate.py): Search literature and validate/refine novelty

Orchestrates both phases to generate hypotheses with dynamic literature access.
"""

import logging
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from co_scientist.nodes.generation.citations import ReferenceIndex

# pylint: disable=wrong-import-position
from co_scientist.mcp_client import get_mcp_client
from co_scientist.models import Hypothesis
from co_scientist.state import WorkflowState
from co_scientist.nodes.generation.literature_tools.draft import (
    draft_hypotheses,)
from co_scientist.nodes.generation.literature_tools.validate import (
    validate_hypotheses,)
# pylint: enable=wrong-import-position

logger = logging.getLogger(__name__)


async def generate_with_tools(
    state: WorkflowState,
    count: int,
    reference_index: Optional["ReferenceIndex"] = None,
) -> list[Hypothesis]:
    """Generates hypotheses with two-phase tool-based process
    (draft -> validate).

    Phase 1: draft hypotheses by reading papers and identifying gaps
    Phase 2: validate novelty by searching and refining/pivoting

    Args:
        state: Current workflow state
        count: Number of hypotheses to generate
        reference_index: Citation key → source mapping for structured citations

    Returns:
        List of validated hypotheses with generation_method="literature_tools"
    """
    logger.info("Generating %s hypotheses with two-phase tool-based process",
                count)

    # Resolved once and threaded into both draft_hypotheses() and
    # validate_hypotheses() below, so both phases resolve tool whitelists
    # from the same registry (see the fallback logic in draft.py/validate.py).
    tool_registry = state.get("tool_registry")

    # Re-raised after logging: without an MCP client neither phase can read
    # or search literature, so this must abort generation, not degrade.
    try:
        mcp_client = await get_mcp_client(tool_registry=tool_registry)
    except Exception as e:
        logger.warning("Failed to get MCP client: %s", e)
        raise

    # Diagnostic-only block: reports how much literature-review context is
    # already warm-started before drafting begins vs. how much the draft
    # agent will need to search for itself. Does not affect control flow.
    articles = state.get("articles", [])
    if articles:
        # used_in_analysis marks articles literature review actually read
        # (vs. merely fetched), the real warm-start signal for drafting.
        used_count = sum(1 for art in articles if art.used_in_analysis)
        logger.debug(
            "state.articles contains %s total articles,"
            " %s with used_in_analysis=True", len(articles), used_count)
        if used_count > 0:
            # Split further for logging only: PDF-backed articles carry
            # full text into the draft prompt; abstract-only ones carry less.
            articles_with_pdfs = sum(
                1 for art in articles if art.used_in_analysis and art.pdf_links)
            logger.info(
                "Including %s analyzed articles in prompt"
                " (%s with PDFs, %s abstract-only)", used_count,
                articles_with_pdfs, used_count - articles_with_pdfs)
        else:
            # No warm-started reading context available; Phase 1 falls back
            # to discovering and reading literature via its own tool calls.
            logger.warning(
                "No articles with used_in_analysis=True found in state"
                " - agent will search fresh")

    # Phase 1: read papers (warm-started and freshly searched) and draft
    # initial hypothesis ideas from gaps identified in the literature.
    draft_hyps = await draft_hypotheses(
        state=state,
        count=count,
        mcp_client=mcp_client,
        tool_registry=tool_registry,
        reference_index=reference_index,
    )

    logger.info("Phase 1 complete: drafted %s hypotheses", len(draft_hyps))

    # Phase 2: search for competing/prior work per draft and decide
    # approve/refine/pivot. Output is tagged
    # GenerationMethod.LITERATURE_TOOLS inside hypothesis_from_llm_output
    # (citations.py), which validate_hypotheses calls per hypothesis.
    hypotheses = await validate_hypotheses(
        state=state,
        draft_hypotheses=draft_hyps,
        mcp_client=mcp_client,
        tool_registry=tool_registry,
        reference_index=reference_index,
    )

    logger.info("Phase 2 complete: validated %s hypotheses", len(hypotheses))

    # Debug trace of the final generation_method/text for every hypothesis
    # produced by this two-phase pipeline.
    for i, hyp in enumerate(hypotheses):
        method = hyp.generation_method
        logger.debug(
            "tool-generated hypothesis %s: generation_method=%s, text=%s...",
            i + 1, method.value if method else None, hyp.text[:80])

    return hypotheses


__all__ = ["draft_hypotheses", "validate_hypotheses", "generate_with_tools"]
