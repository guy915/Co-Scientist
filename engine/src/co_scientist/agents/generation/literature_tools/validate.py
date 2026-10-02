"""Validate draft novelty, then synthesize approved or refined hypotheses."""

import logging
from typing import TYPE_CHECKING, Any, Optional

from co_scientist.agents.generation.literature_tools.validate_novelty import (
    _build_novelty_analysis_prompt as _build_novelty_analysis_prompt,
)
from co_scientist.agents.generation.literature_tools.validate_novelty import (
    _run_novelty_analysis_stage,
)
from co_scientist.agents.generation.literature_tools.validate_search import (
    _NoveltySearchContext,
)
from co_scientist.agents.generation.literature_tools.validate_support import (
    _batch_hypotheses_for_synthesis,
    _build_synthesis_context,
    _run_and_retry_synthesis_batches,
)
from co_scientist.agents.generation.literature_tools.validate_support import (
    _build_paper_metadata as _build_paper_metadata,
)
from co_scientist.agents.generation.literature_tools.validate_support import (
    _build_synthesis_prompt_metadata as _build_synthesis_prompt_metadata,
)
from co_scientist.agents.generation.literature_tools.validate_support import (
    _synthesis_tool_contract as _synthesis_tool_contract,
)
from co_scientist.agents.generation.literature_tools.validate_synthesis import (
    _build_hypotheses_from_synthesis,
    _build_synthesis_call_inputs,
    _log_synthesis_tool_call_summary,
    _parse_synthesis_response,
)
from co_scientist.agents.generation.literature_tools.validate_synthesis import (
    _SynthesisCallInputs as _SynthesisCallInputs,
)
from co_scientist.agents.generation.literature_tools.validate_synthesis import (
    _SynthesisContext as _SynthesisContext,
)
from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    HIGH_TEMPERATURE,
    corpus_slug,
)
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    ToolLoop,
    call_llm_json,
    call_llm_with_tools,
)
from co_scientist.models import Hypothesis
from co_scientist.schemas import HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA
from co_scientist.state import WorkflowState

if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry

logger = logging.getLogger(__name__)


async def _call_novelty_analysis_llm(
    prompt: str, model_name: str
) -> dict[str, Any]:
    """Call the novelty-analysis LLM and return the structured analysis."""
    return await call_llm_json(
        prompt=prompt,
        spec=CompletionSpec(
            model_name=model_name,
            max_tokens=EXTENDED_MAX_TOKENS,
            temperature=HIGH_TEMPERATURE,
            json_schema=HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA,
        ),
    )


async def _analyze_paper_novelty(
    hypothesis_text: str,
    hypothesis_idx: int,
    paper_id: str,
    metadata: dict[str, Any],
    model_name: str,
) -> dict[str, Any] | None:
    """Analyze a single paper's novelty relative to one draft hypothesis."""
    prompt = _build_novelty_analysis_prompt(hypothesis_text, metadata)

    try:
        analysis = await _call_novelty_analysis_llm(prompt, model_name)
    except TASK_CONTROL_FLOW_ERRORS:
        raise
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


async def _invoke_synthesis_llm(
    call_inputs: _SynthesisCallInputs,
    batch_label: str,
    batch_size: int,
    already_validated_texts: list[str] | None,
    ctx: _SynthesisContext,
) -> tuple[str, dict[str, int]]:
    """Call the synthesis LLM with tools for one batch and return its result."""
    tracked_executor, tool_call_counts = ctx.provider.tracked_executor(
        f"Validation batch {batch_label}"
    )
    final_response, _ = await call_llm_with_tools(
        prompt=call_inputs.prompt,
        spec=CompletionSpec(
            model_name=ctx.state["model_name"],
            max_tokens=call_inputs.max_tokens,
            temperature=HIGH_TEMPERATURE,
        ),
        loop=ToolLoop(
            tools=ctx.openai_tools,
            executor=tracked_executor,
            max_iterations=ctx.max_iterations,
            tool_contract=_synthesis_tool_contract(ctx.tool_registry),
        ),
        options=LLMCallOptions(
            run_id=ctx.state.get("run_id"),
            prompt_name=f"validation_synthesis_batch_{batch_label}",
            prompt_metadata=_build_synthesis_prompt_metadata(
                batch_label,
                batch_size,
                ctx.max_iterations,
                already_validated_texts,
            ),
        ),
    )
    return final_response, tool_call_counts


async def validate_hypotheses(
    state: WorkflowState,
    draft_hypotheses: list[dict[str, str]],
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"] = None,
    reference_index: Any | None = None,
) -> tuple[list[Hypothesis], int]:
    """Phase 2: validate novelty and refine/pivot drafts."""
    logger.info(
        "Phase 2: Validating %s draft hypotheses", len(draft_hypotheses)
    )
    hypotheses_with_analyses = await _run_validate_novelty_stage(
        draft_hypotheses, state, mcp_client, tool_registry
    )
    hypotheses = await _run_synthesis_and_build_hypotheses(
        hypotheses_with_analyses,
        state,
        mcp_client,
        tool_registry,
        reference_index,
    )
    return hypotheses, _count_validation_llm_calls(hypotheses_with_analyses)


async def _run_single_synthesis_call(
    batch: list[dict[str, Any]],
    batch_label: str,
    already_validated_texts: list[str] | None,
    ctx: _SynthesisContext,
) -> list[dict[str, Any]]:
    """Run one synthesis batch call and return the parsed hypotheses list."""
    batch_size = len(batch)
    logger.info(
        "Processing synthesis batch %s (%s hypotheses)", batch_label, batch_size
    )

    call_inputs = _build_synthesis_call_inputs(
        batch, batch_label, already_validated_texts, ctx
    )

    final_response, tool_call_counts = await _invoke_synthesis_llm(
        call_inputs,
        batch_label,
        batch_size,
        already_validated_texts,
        ctx,
    )
    _log_synthesis_tool_call_summary(batch_label, tool_call_counts)

    return _parse_synthesis_response(final_response, batch_label)


async def _run_synthesis_stage_batches(
    hypotheses_with_analyses: list[dict[str, Any]],
    ctx: _SynthesisContext,
) -> list[dict[str, Any]]:
    """Batch, run, and retry-on-failure the synthesis stage for all drafts."""
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


async def _run_validation_synthesis_stage(
    hypotheses_with_analyses: list[dict[str, Any]],
    state: WorkflowState,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    reference_index: Any | None,
) -> list[dict[str, Any]]:
    """Run Stage 2: synthesize approve/refine/pivot decisions for all drafts."""
    ctx = _build_synthesis_context(
        hypotheses_with_analyses,
        state,
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
) -> list[dict[str, Any]]:
    """Derive the shared corpus slug and run Stage 1 novelty analysis."""
    # Same deterministic slug the draft phase used (warm corpus reuse).
    shared_slug = corpus_slug(state["research_goal"])
    logger.info("Reusing shared corpus from draft phase: %s", shared_slug)

    search_ctx = _NoveltySearchContext(
        mcp_client=mcp_client,
        tool_registry=tool_registry,
        shared_slug=shared_slug,
        run_id=state.get("run_id"),
    )

    # The per-paper analyzer is threaded in so its call_llm_json seam
    # resolves through validate.py's namespace (tests monkeypatch it
    # there).
    return await _run_novelty_analysis_stage(
        draft_hypotheses,
        state,
        search_ctx,
        analyze_paper=_analyze_paper_novelty,
    )


async def _run_synthesis_and_build_hypotheses(
    hypotheses_with_analyses: list[dict[str, Any]],
    state: WorkflowState,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    reference_index: Any | None,
) -> list[Hypothesis]:
    """Run Stage 2 synthesis and build the final validated Hypothesis list."""
    all_validated_hypotheses = await _run_validation_synthesis_stage(
        hypotheses_with_analyses,
        state,
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


def _count_validation_llm_calls(
    hypotheses_with_analyses: list[dict[str, Any]],
) -> int:
    """Estimate successful novelty calls plus one call per synthesis batch.

    Failures, physical retries, and synthesis tool turns can spend more calls;
    this floor retains the legacy node metric alongside transport telemetry.
    """
    novelty_calls = sum(
        len(item.get("novelty_analyses") or [])
        for item in hypotheses_with_analyses
    )
    synthesis_calls = len(
        _batch_hypotheses_for_synthesis(hypotheses_with_analyses)
    )
    return novelty_calls + synthesis_calls
