"""Phase 4: literature review synthesis.

Synthesizes across the per-paper analyses (optionally weaving in Phase 2.6
knowledge-graph context) into the ``articles_with_reasoning`` text. Degrades
to the ``LITERATURE_REVIEW_FAILED`` sentinel only when there is nothing to
synthesize from; a synthesis LLM call failing over a non-empty
``paper_analyses`` degrades to a deterministic roll-up instead (see
``_build_fallback_synthesis``), since retrieval already paid the real LLM
cost that produced those analyses and losing the synthesis prose must not
also discard them.
"""

import logging
from typing import Any

from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    HIGH_TEMPERATURE,
    LITERATURE_REVIEW_FAILED,
    LITERATURE_SYNTHESIS_FALLBACK_MAX_CHARS,
    truncate,
)
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm,
)
from co_scientist.prompts import get_literature_review_synthesis_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


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
