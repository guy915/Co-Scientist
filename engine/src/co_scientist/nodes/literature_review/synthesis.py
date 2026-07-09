"""Phase 4: literature review synthesis.

Synthesizes across the per-paper analyses (optionally weaving in Phase 2.6
knowledge-graph context) into the ``articles_with_reasoning`` text. Degrades
to the ``LITERATURE_REVIEW_FAILED`` sentinel when there is nothing to
synthesize or the synthesis LLM call fails.
"""

import logging
from typing import Any

from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    HIGH_TEMPERATURE,
    LITERATURE_REVIEW_FAILED,
)
from co_scientist.llm import call_llm
from co_scientist.prompts import get_literature_review_synthesis_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


async def _run_synthesis_llm(
    paper_analyses: list[dict[str, Any]],
    state: WorkflowState,
    background_context: str,
) -> str:
    """Builds the synthesis prompt and calls the LLM.

    Args:
        paper_analyses: Per-paper analyses produced by Phase 3.
        state: Current workflow state.
        background_context: The (possibly empty) Phase 2.6 knowledge-graph
            text; the synthesis prompt weaves it in alongside the per-paper
            analyses so the LLM can ground statements in both.

    Returns:
        The synthesis text.
    """
    prompt = get_literature_review_synthesis_prompt(
        research_goal=state["research_goal"],
        paper_analyses=paper_analyses,
        background_context=background_context,
    )

    logger.info(
        "Calling synthesis LLM with %s chars, %s papers",
        len(prompt),
        len(paper_analyses),
    )

    synthesis = await call_llm(
        prompt=prompt,
        model_name=state["model_name"],
        max_tokens=EXTENDED_MAX_TOKENS,
        temperature=HIGH_TEMPERATURE,
        run_id=state.get("run_id"),
        prompt_name="literature_review_synthesis",
        prompt_metadata={
            "prompt_length_chars": len(prompt),
            "papers_analyzed": len(paper_analyses),
        },
    )

    logger.info("Synthesis complete - length: %s chars", len(synthesis))
    logger.debug("Synthesis preview: %s...", synthesis[:500])

    return synthesis


async def _phase4_synthesize(
    paper_analyses: list[dict[str, Any]],
    state: WorkflowState,
    background_context: str = "",
) -> str:
    """Phase 4: Synthesize across papers to create articles_with_reasoning."""
    if not paper_analyses:
        # No analyses to synthesize from: return the failure sentinel so
        # downstream generation nodes fall back to no-literature mode
        # instead of treating an empty synthesis as valid grounding.
        logger.error("No paper analyses available for synthesis")
        return LITERATURE_REVIEW_FAILED

    logger.info("Phase 4: synthesizing across papers")

    try:
        return await _run_synthesis_llm(
            paper_analyses, state, background_context
        )

    except Exception as e:  # pylint: disable=broad-exception-caught
        # Synthesis failure also degrades to the sentinel rather than
        # propagating, consistent with the empty-analyses branch above.
        logger.error("Synthesis failed: %s", e)
        return LITERATURE_REVIEW_FAILED
