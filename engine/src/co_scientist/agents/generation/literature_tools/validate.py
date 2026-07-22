"""Phase 2 on lit-tool-based generation: Validate novelty and refine/pivot.

This phase uses a two-stage approach:
1. Per-hypothesis per-paper novelty analysis (parallel)
2. Synthesis agent decides approve/refine/pivot based on analyses (with tool
access)

The helpers live in sibling modules (validate_search.py, validate_novelty.py,
validate_synthesis.py); the two LLM seams (call_llm_json for the per-paper
novelty analysis and call_llm_with_tools for the synthesis agent) are called
from this module so tests can monkeypatch them on this namespace. All helper
names are re-exported here for compatibility.
"""

import logging
from typing import TYPE_CHECKING, Any, Optional

from co_scientist.agents.generation.literature_tools.validate_novelty import (
    _build_novelty_analysis_prompt as _build_novelty_analysis_prompt,
)
from co_scientist.agents.generation.literature_tools.validate_novelty import (
    _gather_hypothesis_novelty_analyses as _gather_hypothesis_novelty_analyses,
)
from co_scientist.agents.generation.literature_tools.validate_novelty import (
    _run_novelty_analysis_stage as _run_novelty_analysis_stage,
)
from co_scientist.agents.generation.literature_tools.validate_novelty import (
    _run_parallel_novelty_analyses as _run_parallel_novelty_analyses,
)
from co_scientist.agents.generation.literature_tools.validate_search import (
    _articles_to_paper_dict as _articles_to_paper_dict,
)
from co_scientist.agents.generation.literature_tools.validate_search import (
    _find_search_tool as _find_search_tool,
)
from co_scientist.agents.generation.literature_tools.validate_search import (
    _first as _first,
)
from co_scientist.agents.generation.literature_tools.validate_search import (
    _search_papers_for_hypothesis as _search_papers_for_hypothesis,
)
from co_scientist.agents.generation.literature_tools.validate_search import (
    _search_papers_legacy_fallback as _search_papers_legacy_fallback,
)
from co_scientist.agents.generation.literature_tools.validate_search import (
    _search_papers_via_tool_config as _search_papers_via_tool_config,
)
from co_scientist.agents.generation.literature_tools.validate_synthesis import (
    _build_hypotheses_from_synthesis as _build_hypotheses_from_synthesis,
)
from co_scientist.agents.generation.literature_tools.validate_synthesis import (
    _build_synthesis_call_inputs as _build_synthesis_call_inputs,
)
from co_scientist.agents.generation.literature_tools.validate_synthesis import (
    _log_synthesis_tool_call_summary as _log_synthesis_tool_call_summary,
)
from co_scientist.agents.generation.literature_tools.validate_synthesis import (
    _parse_synthesis_response as _parse_synthesis_response,
)
from co_scientist.agents.generation.literature_tools.validate_synthesis import (
    _retry_failed_synthesis_batches as _retry_failed_synthesis_batches,
)
from co_scientist.agents.generation.literature_tools.validate_synthesis import (
    _retry_one_hypothesis as _retry_one_hypothesis,
)
from co_scientist.agents.generation.literature_tools.validate_synthesis import (
    _run_synthesis_batches as _run_synthesis_batches,
)
from co_scientist.agents.generation.literature_tools.validate_synthesis import (
    _setup_validation_tool_provider as _setup_validation_tool_provider,
)
from co_scientist.agents.generation.literature_tools.validate_synthesis import (
    _SynthesisCaller as _SynthesisCaller,
)
from co_scientist.agents.generation.literature_tools.validate_synthesis import (
    _SynthesisContext as _SynthesisContext,
)
from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    HIGH_TEMPERATURE,
    VALIDATION_SYNTHESIS_BATCH_SIZE,
    corpus_slug,
)
from co_scientist.llm import call_llm_json, call_llm_with_tools
from co_scientist.models import Hypothesis
from co_scientist.schemas import HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA
from co_scientist.state import WorkflowState

if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry

logger = logging.getLogger(__name__)


async def _call_novelty_analysis_llm(
    prompt: str, model_name: str
) -> dict[str, Any]:
    """Call the novelty-analysis LLM and return the structured analysis.

    Args:
        prompt: the per-paper novelty-analysis prompt.
        model_name: model to use for the novelty-analysis LLM call.

    Returns:
        The structured novelty-analysis result.
    """
    return await call_llm_json(
        prompt=prompt,
        model_name=model_name,
        json_schema=HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA,
        max_tokens=EXTENDED_MAX_TOKENS,
        temperature=HIGH_TEMPERATURE,
    )


def _build_paper_metadata(
    paper_id: str, metadata: dict[str, Any]
) -> dict[str, Any]:
    """Build the paper_metadata sub-dict for a novelty analysis result.

    Args:
        paper_id: identifier for the paper within its hypothesis's paper
            set.
        metadata: paper metadata dict (title/authors/year/fulltext).

    Returns:
        The paper_metadata dict.
    """
    return {
        "paper_id": paper_id,
        "title": metadata.get("title", "Unknown"),
        "year": metadata.get("year"),
        "authors": metadata.get("authors", []),
    }


async def _analyze_paper_novelty(
    hypothesis_text: str,
    hypothesis_idx: int,
    paper_id: str,
    metadata: dict[str, Any],
    model_name: str,
) -> dict[str, Any] | None:
    """Analyze a single paper's novelty relative to one draft hypothesis.

    Args:
        hypothesis_text: text of the draft hypothesis being validated.
        hypothesis_idx: 1-based index of the hypothesis, for log messages.
        paper_id: identifier for the paper within its hypothesis's paper set.
        metadata: paper metadata dict (title/authors/year/fulltext).
        model_name: model to use for the novelty-analysis LLM call.

    Returns:
        Dict with "paper_metadata" and "analysis" keys, or None if the
        analysis call failed (failures are logged, not raised, so one bad
        paper does not abort the hypothesis's whole novelty analysis).
    """
    prompt = _build_novelty_analysis_prompt(hypothesis_text, metadata)

    try:
        analysis = await _call_novelty_analysis_llm(prompt, model_name)
    except Exception as e:
        logger.error(
            "Failed to analyze paper %s for hypothesis %s: %s",
            paper_id,
            hypothesis_idx,
            e,
        )
        # None is filtered out by the caller rather than aborting the whole
        # hypothesis's novelty analysis over one bad paper.
        return None

    return {
        "paper_metadata": _build_paper_metadata(paper_id, metadata),
        "analysis": analysis,
    }


def _build_synthesis_prompt_metadata(
    batch_label: str,
    batch_size: int,
    max_iterations: int,
    already_validated_texts: list[str] | None,
) -> dict[str, Any]:
    """Build the prompt_metadata dict logged with a synthesis batch call.

    Args:
        batch_label: label identifying this batch, used in logging.
        batch_size: number of hypotheses in this batch.
        max_iterations: iteration budget for this synthesis call.
        already_validated_texts: hypothesis texts already validated in
            prior batches/retries, or None.

    Returns:
        The prompt_metadata dict for call_llm_with_tools.
    """
    return {
        "batch_label": batch_label,
        "batch_size": batch_size,
        "max_iterations": max_iterations,
        "retry_context_count": len(already_validated_texts)
        if already_validated_texts
        else 0,
    }


async def _invoke_synthesis_llm(
    synthesis_prompt: str,
    synthesis_max_tokens: int,
    batch_label: str,
    batch_size: int,
    already_validated_texts: list[str] | None,
    ctx: _SynthesisContext,
) -> tuple[str, dict[str, int]]:
    """Call the synthesis LLM with tools for one batch and return its result.

    Args:
        synthesis_prompt: the assembled synthesis prompt for this batch.
        synthesis_max_tokens: token budget for this synthesis call.
        batch_label: label identifying this batch, used in logging.
        batch_size: number of hypotheses in this batch.
        already_validated_texts: already-validated texts, or None.
        ctx: shared per-call synthesis state.

    Returns:
        Tuple of (response text, per-tool call counts).
    """
    tracked_executor, tool_call_counts = ctx.provider.tracked_executor(
        f"Validation batch {batch_label}"
    )
    final_response, _ = await call_llm_with_tools(
        prompt=synthesis_prompt,
        model_name=ctx.state["model_name"],
        tools=ctx.openai_tools,
        tool_executor=tracked_executor,
        max_tokens=synthesis_max_tokens,
        temperature=HIGH_TEMPERATURE,
        max_iterations=ctx.max_iterations,
        run_id=ctx.state.get("run_id"),
        prompt_name=f"validation_synthesis_batch_{batch_label}",
        prompt_metadata=_build_synthesis_prompt_metadata(
            batch_label, batch_size, ctx.max_iterations, already_validated_texts
        ),
    )
    return final_response, tool_call_counts


async def _run_single_synthesis_call(
    batch: list[dict[str, Any]],
    batch_label: str,
    already_validated_texts: list[str] | None,
    ctx: _SynthesisContext,
) -> list[dict[str, Any]]:
    """Run one synthesis batch call and return the parsed hypotheses list.

    already_validated_texts lets a retry see prior validated texts, so the
    synthesis agent is less likely to produce a near-duplicate.

    Args:
        batch: hypothesis batch (with novelty analyses) to synthesize.
        batch_label: label identifying this batch, used in logging.
        already_validated_texts: prior validated texts, or None.
        ctx: shared per-call synthesis state.

    Returns:
        The parsed "hypotheses" list from the synthesis response.
    """
    batch_size = len(batch)
    logger.info(
        "Processing synthesis batch %s (%s hypotheses)", batch_label, batch_size
    )

    synthesis_prompt, synthesis_max_tokens = _build_synthesis_call_inputs(
        batch, batch_label, already_validated_texts, ctx
    )

    final_response, tool_call_counts = await _invoke_synthesis_llm(
        synthesis_prompt,
        synthesis_max_tokens,
        batch_label,
        batch_size,
        already_validated_texts,
        ctx,
    )
    _log_synthesis_tool_call_summary(batch_label, tool_call_counts)

    return _parse_synthesis_response(final_response, batch_label)


def _batch_hypotheses_for_synthesis(
    hypotheses_with_analyses: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Split Stage 1 output into fixed-size batches for synthesis calls.

    Args:
        hypotheses_with_analyses: Stage 1 output, one dict per draft with
            "draft" and "novelty_analyses" keys.

    Returns:
        List of batches, each up to VALIDATION_SYNTHESIS_BATCH_SIZE long.
    """
    batches = [
        hypotheses_with_analyses[i : i + VALIDATION_SYNTHESIS_BATCH_SIZE]
        for i in range(
            0, len(hypotheses_with_analyses), VALIDATION_SYNTHESIS_BATCH_SIZE
        )
    ]
    logger.info(
        "Split into %s batches of up to %s hypotheses",
        len(batches),
        VALIDATION_SYNTHESIS_BATCH_SIZE,
    )
    return batches


async def _run_and_retry_synthesis_batches(
    batches: list[list[dict[str, Any]]],
    call_synthesis: _SynthesisCaller,
) -> list[dict[str, Any]]:
    """Run every batch and retry any failures one hypothesis at a time.

    Args:
        batches: hypothesis batches to run synthesis over.
        call_synthesis: the synthesis callable to invoke per batch/retry.

    Returns:
        List of validated hypothesis dicts from all batches (including
        individually-retried ones).
    """
    all_validated_hypotheses, failed_batches = await _run_synthesis_batches(
        batches, call_synthesis
    )

    if failed_batches:
        await _retry_failed_synthesis_batches(
            failed_batches, all_validated_hypotheses, call_synthesis
        )

    return all_validated_hypotheses


async def _run_synthesis_stage_batches(
    hypotheses_with_analyses: list[dict[str, Any]],
    ctx: _SynthesisContext,
) -> list[dict[str, Any]]:
    """Batch, run, and retry-on-failure the synthesis stage for all drafts.

    Executes all batches in parallel, capturing failures without aborting,
    then retries any failed batch one hypothesis at a time.

    Args:
        hypotheses_with_analyses: Stage 1 output, one dict per draft.
        ctx: shared per-call synthesis state.

    Returns:
        List of validated hypothesis dicts from all batches.
    """
    batches = _batch_hypotheses_for_synthesis(hypotheses_with_analyses)

    # Closes over ctx to match the _SynthesisCaller signature used by the
    # batch-execution/retry helpers below.
    async def _call_synthesis(
        batch: list[dict[str, Any]],
        batch_label: str,
        already_validated_texts: list[str] | None,
    ) -> list[dict[str, Any]]:
        """Run one synthesis call and return the parsed hypotheses list."""
        return await _run_single_synthesis_call(
            batch, batch_label, already_validated_texts, ctx
        )

    all_validated_hypotheses = await _run_and_retry_synthesis_batches(
        batches, _call_synthesis
    )
    logger.info(
        "Combined %s validated hypotheses from %s batches",
        len(all_validated_hypotheses),
        len(batches),
    )
    return all_validated_hypotheses


def _build_synthesis_context(
    hypotheses_with_analyses: list[dict[str, Any]],
    state: WorkflowState,
    research_goal: str,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    reference_index: Any | None,
) -> _SynthesisContext:
    """Resolve the tool provider and assemble the shared synthesis context.

    Args:
        hypotheses_with_analyses: Stage 1 output, sized for iteration budget.
        state: current workflow state.
        research_goal: the run's research goal text.
        mcp_client: MCP client for tool access.
        tool_registry: optional ToolRegistry for tool selection.
        reference_index: optional citation reference index.

    Returns:
        The shared per-call synthesis context.
    """
    logger.info(
        "Running validation synthesis for %s hypotheses in batches of %s",
        len(hypotheses_with_analyses),
        VALIDATION_SYNTHESIS_BATCH_SIZE,
    )
    provider, openai_tools, tool_registry, max_iterations = (
        _setup_validation_tool_provider(
            mcp_client, tool_registry, len(hypotheses_with_analyses)
        )
    )
    return _SynthesisContext(
        state,
        research_goal,
        max_iterations,
        tool_registry,
        reference_index,
        provider,
        openai_tools,
    )


async def _run_validation_synthesis_stage(
    hypotheses_with_analyses: list[dict[str, Any]],
    state: WorkflowState,
    research_goal: str,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    reference_index: Any | None,
) -> list[dict[str, Any]]:
    """Run Stage 2: synthesize approve/refine/pivot decisions for all drafts.

    The synthesis agent has tool access for searching additional papers
    when pivoting.

    Args:
        hypotheses_with_analyses: Stage 1 output, one dict per draft with
            "draft" and "novelty_analyses" keys.
        state: current workflow state.
        research_goal: the run's research goal text.
        mcp_client: MCP client for tool access.
        tool_registry: optional ToolRegistry for config-driven tool
            selection.
        reference_index: optional citation reference index supplying the
            `[C*]` reference list.

    Returns:
        List of validated hypothesis dicts from all batches (including
        individually-retried ones).
    """
    ctx = _build_synthesis_context(
        hypotheses_with_analyses,
        state,
        research_goal,
        mcp_client,
        tool_registry,
        reference_index,
    )
    return await _run_synthesis_stage_batches(hypotheses_with_analyses, ctx)


async def _run_validate_novelty_stage(
    draft_hypotheses: list[dict[str, str]],
    state: WorkflowState,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
) -> tuple[list[dict[str, Any]], str]:
    """Derive the shared corpus slug and run Stage 1 novelty analysis.

    Args:
        draft_hypotheses: list of draft dicts from Phase 1.
        state: current workflow state.
        mcp_client: MCP client for tool access.
        tool_registry: optional ToolRegistry for config-driven tool
            selection.

    Returns:
        Tuple of (Stage 1 output, research goal text).
    """
    research_goal = state["research_goal"]

    # Same deterministic slug the draft phase used (warm corpus reuse).
    shared_slug = corpus_slug(research_goal)
    logger.info("Reusing shared corpus from draft phase: %s", shared_slug)

    # The per-paper analyzer is threaded in so its call_llm_json seam
    # resolves through this module's namespace (tests monkeypatch it here).
    hypotheses_with_analyses = await _run_novelty_analysis_stage(
        draft_hypotheses,
        state,
        mcp_client,
        tool_registry,
        shared_slug,
        state.get("run_id"),
        analyze_paper=_analyze_paper_novelty,
    )

    return hypotheses_with_analyses, research_goal


async def _run_synthesis_and_build_hypotheses(
    hypotheses_with_analyses: list[dict[str, Any]],
    state: WorkflowState,
    research_goal: str,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    reference_index: Any | None,
) -> list[Hypothesis]:
    """Run Stage 2 synthesis and build the final validated Hypothesis list.

    Args:
        hypotheses_with_analyses: Stage 1 output, one dict per draft.
        state: current workflow state.
        research_goal: the run's research goal text.
        mcp_client: MCP client for tool access.
        tool_registry: optional ToolRegistry for config-driven tool
            selection.
        reference_index: optional citation reference index supplying the
            `[C*]` reference list and source map.

    Returns:
        list of validated Hypothesis objects with novelty_validation.
    """
    all_validated_hypotheses = await _run_validation_synthesis_stage(
        hypotheses_with_analyses,
        state,
        research_goal,
        mcp_client,
        tool_registry,
        reference_index,
    )

    # Order matches hypotheses_with_analyses order (batched sequentially).
    hypotheses = _build_hypotheses_from_synthesis(
        all_validated_hypotheses, reference_index
    )
    logger.info("Generated %s validated hypotheses", len(hypotheses))
    return hypotheses


async def validate_hypotheses(
    state: WorkflowState,
    draft_hypotheses: list[dict[str, str]],
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"] = None,
    reference_index: Any | None = None,
) -> list[Hypothesis]:
    """Phase 2: validate novelty and refine/pivot drafts.

    Two-stage approach: (1) per-hypothesis per-paper novelty analysis
    (parallel), (2) synthesis agent decides approve/refine/pivot (with
    tool access for pivoting).

    Args:
        state: current workflow state
        draft_hypotheses: list of draft dicts from Phase 1
        mcp_client: MCP client for tool access
        tool_registry: optional ToolRegistry for config-driven tool selection
        reference_index: optional citation reference index supplying the
            `[C*]` reference list and source map

    Returns:
        list of validated Hypothesis objects with novelty_validation
    """
    logger.info(
        "Phase 2: Validating %s draft hypotheses", len(draft_hypotheses)
    )
    hypotheses_with_analyses, research_goal = await _run_validate_novelty_stage(
        draft_hypotheses, state, mcp_client, tool_registry
    )
    return await _run_synthesis_and_build_hypotheses(
        hypotheses_with_analyses,
        state,
        research_goal,
        mcp_client,
        tool_registry,
        reference_index,
    )
