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
    year = parse_year_from_metadata(metadata)
    # Bound paper text so one long document cannot consume the analysis budget.

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
    try:
        return await _run_paper_analysis_llm(paper_id, metadata, research_goal, model_name)
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception as e:
        # A failed paper must not prevent synthesis from successful analyses.

        logger.error("Failed to analyze paper %s: %s", paper_id, e)
        return None


def _log_sample_analysis(analyses: list[dict[str, Any]]) -> None:
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
    # Metadata alone must never count as analyzed evidence.

    papers_with_content = get_papers_with_content(all_paper_metadata)

    if not papers_with_content:
        logger.error("No papers have content for analysis")
        return []

    logger.info("Phase 3: analyzing %s papers (parallel)", len(papers_with_content))

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
    prompt = get_literature_review_synthesis_prompt(
        research_goal=state["research_goal"],
        paper_analyses=paper_analyses,
        background_context=background_context,
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
        ),
    )

    logger.info("Synthesis complete - length: %s chars", len(synthesis))
    logger.debug("Synthesis preview: %s...", synthesis[:500])

    return synthesis


_FALLBACK_MIN_FIELD_CHARS = 40

"""Keep each field legible in large pools; final truncation still bounds
the whole roll-up when this floor exceeds its per-paper allowance."""


def _fallback_field_budget(paper_count: int, header_len: int) -> int:
    """Share the cap across papers and fields so long early entries cannot
    crowd later papers out."""
    remaining = max(LITERATURE_SYNTHESIS_FALLBACK_MAX_CHARS - header_len, 0)
    per_paper = remaining // max(paper_count, 1)
    return max(per_paper // 4, _FALLBACK_MIN_FIELD_CHARS)


def _format_fallback_entry(index: int, entry: dict[str, Any], field_chars: int) -> str:
    """Keep findings, gaps and unexplored areas: these feed generation,
    unlike reader-only analysis fields."""
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
    """Preserve analyzed evidence when synthesis fails without pretending
    cross-paper synthesis succeeded; bound every paper's share."""
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
    if not paper_analyses:
        # Without analyses, preserve the no-grounding sentinel for downstream
        # generation.

        logger.error("No paper analyses available for synthesis")
        return LITERATURE_REVIEW_FAILED

    logger.info("Phase 4: synthesizing across papers")

    try:
        return await _run_synthesis_llm(paper_analyses, state, background_context)

    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception as e:
        # Failed synthesis must not discard costly real analyses; retain them in
        # a bounded roll-up.

        logger.error(
            "Synthesis failed: %s -- degrading to a deterministic roll-up of %s paper analyses",
            e,
            len(paper_analyses),
        )
        return _build_fallback_synthesis(paper_analyses)
