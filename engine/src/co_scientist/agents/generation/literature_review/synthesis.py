"""Analyze collected literature and synthesize its scientific context."""

import asyncio
import logging
from typing import Any

from co_scientist.constants import (
    DEFAULT_MAX_TOKENS,
    EXTENDED_MAX_TOKENS,
    HIGH_TEMPERATURE,
    LITERATURE_REVIEW_FAILED,
    LITERATURE_SYNTHESIS_FALLBACK_MAX_CHARS,
    truncate,
)
from co_scientist.evidence.article_support import (
    get_paper_content_for_analysis,
    get_papers_with_content,
    parse_year_from_metadata,
)
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm,
    call_llm_json,
)
from co_scientist.prompts import (
    get_literature_review_paper_analysis_prompt,
    get_literature_review_synthesis_prompt,
)
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


def _build_synthesis_prompt(
    paper_analyses: list[dict[str, Any]],
    state: WorkflowState,
    background_context: str,
) -> str:
    """Builds the synthesis prompt and logs the upcoming LLM call.

    background_context is the (possibly empty) Phase 2.6 knowledge-graph
    text; the synthesis prompt weaves it in alongside the per-paper analyses
    so the LLM can ground statements in both.
    """
    prompt = get_literature_review_synthesis_prompt(
        research_goal=state["research_goal"],
        paper_analyses=paper_analyses,
        background_context=background_context,
        # Audit E7: focus the gap analysis on what the meta-review flags
        # as missing or weak. Empty on iteration 1.
        meta_review=state.get("meta_review"),
    )

    logger.info(
        "Calling synthesis LLM with %s chars, %s papers",
        len(prompt),
        len(paper_analyses),
    )
    return prompt


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
    prompt = _build_synthesis_prompt(paper_analyses, state, background_context)

    synthesis = await call_llm(
        prompt=prompt,
        spec=CompletionSpec(
            model_name=state["model_name"],
            max_tokens=EXTENDED_MAX_TOKENS,
            temperature=HIGH_TEMPERATURE,
        ),
        options=LLMCallOptions(
            run_id=state.get("run_id"),
            prompt_name="literature_review_synthesis",
            prompt_metadata={
                "prompt_length_chars": len(prompt),
                "papers_analyzed": len(paper_analyses),
            },
        ),
    )

    logger.info("Synthesis complete - length: %s chars", len(synthesis))
    logger.debug("Synthesis preview: %s...", synthesis[:500])

    return synthesis


_FALLBACK_MIN_FIELD_CHARS = 40

"""Floor on each truncated field in the fallback roll-up. Without a floor,
a large enough paper pool divides the per-paper allowance down to nothing
-- this keeps every entry legible even when papers are numerous, at the
cost of the total running past ``LITERATURE_SYNTHESIS_FALLBACK_MAX_CHARS``
for an extreme pool (the caller's own final ``truncate`` still bounds the
overall output in that case)."""


def _fallback_field_budget(paper_count: int, header_len: int) -> int:
    """Per-field character allowance for the fallback roll-up.

    Splits what is left after the header across every paper, then across
    the four strings (title plus the three analysis fields) each paper
    entry renders -- so a large pool spends the cap thinly across every
    paper instead of the first few papers' untruncated text consuming it
    all before the rest are ever reached.
    """
    remaining = max(LITERATURE_SYNTHESIS_FALLBACK_MAX_CHARS - header_len, 0)
    per_paper = remaining // max(paper_count, 1)
    return max(per_paper // 4, _FALLBACK_MIN_FIELD_CHARS)


def _format_fallback_entry(
    index: int, entry: dict[str, Any], field_chars: int
) -> str:
    """Renders one paper's analysis as a short markdown bullet block.

    Only the three fields most directly useful for spotting an opportunity
    (what was found, what is missing, what nobody has tried) are included
    -- this is a roll-up, not a restatement of the full per-paper analysis.
    Each field is truncated to ``field_chars`` so one paper's long text
    cannot crowd out the papers after it.
    """
    metadata = entry.get("metadata") or {}
    analysis = entry.get("analysis") or {}
    title = metadata.get("title") or f"Untitled paper {index}"
    key_findings = analysis.get("key_findings") or "not recorded"
    gaps = analysis.get("gaps_identified") or "not recorded"
    unexplored = analysis.get("unexplored_areas") or "not recorded"
    return (
        f"{index}. **{truncate(title, field_chars)}**\n"
        f"   - Key findings: {truncate(key_findings, field_chars)}\n"
        f"   - Gaps identified: {truncate(gaps, field_chars)}\n"
        f"   - Unexplored areas: {truncate(unexplored, field_chars)}\n"
    )


def _build_fallback_synthesis(paper_analyses: list[dict[str, Any]]) -> str:
    """Builds a deterministic (no-LLM) roll-up when the synthesis call fails.

    Not a synthesis: nothing here identifies cross-paper themes, spots
    contradictions, or organizes findings thematically the way
    ``_run_synthesis_llm``'s output does -- it is a mechanical listing of
    each paper's own analysis, so a reader is not told a synthesis
    happened when it did not. It exists so that a failed synthesis call
    does not discard papers that cost real LLM calls to retrieve and
    analyze; downstream consumers (``coordinator_strategy.
    _check_literature_availability`` and every generation prompt reading
    ``articles_with_reasoning``) only check for the ``LITERATURE_REVIEW_
    FAILED`` sentinel, so this text is otherwise treated as ordinary
    literature-review context.

    ``gaps_identified`` and ``unexplored_areas`` are both included
    (alongside ``key_findings``) because they are the two
    hypothesis-generative fields -- the whole reason the literature
    review feeds generation is to point it at what is missing and what
    nobody has tried yet. ``methodology_limitations``, ``future_work``
    and ``relevance`` serve a human reader, not the next node, and stay
    out to leave room for the two fields that do.

    Bounded to ``LITERATURE_SYNTHESIS_FALLBACK_MAX_CHARS`` so a large paper
    pool cannot make the roll-up blow a downstream prompt's token budget,
    the way the real synthesis call's own ``max_tokens`` already bounds its
    output -- spent via a per-paper, per-field allowance
    (``_fallback_field_budget``) rather than one global truncation, so a
    large pool still leaves every paper's three signals represented
    instead of the first paper or two consuming the whole cap.
    """
    header = (
        "## Literature Review (unsynthesized -- synthesis step failed)\n\n"
        f"The synthesis LLM call failed, so this is a mechanical roll-up"
        f" of the {len(paper_analyses)} paper(s) successfully analyzed,"
        " not an LLM synthesis. No cross-paper themes, contradictions, or"
        " gaps have been identified -- treat each entry below as an"
        " independent source.\n\n"
    )
    field_chars = _fallback_field_budget(len(paper_analyses), len(header))
    body = "\n".join(
        _format_fallback_entry(i, entry, field_chars)
        for i, entry in enumerate(paper_analyses, start=1)
    )
    return truncate(header + body, LITERATURE_SYNTHESIS_FALLBACK_MAX_CHARS)


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

    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception as e:
        # The analyses themselves are real, LLM-costly retrieval output;
        # losing the synthesis prose must not also discard them, so this
        # degrades to a deterministic roll-up rather than the sentinel
        # (which the empty-analyses branch above still owns).
        logger.error(
            "Synthesis failed: %s -- degrading to a deterministic roll-up"
            " of %s paper analyses",
            e,
            len(paper_analyses),
        )
        return _build_fallback_synthesis(paper_analyses)
