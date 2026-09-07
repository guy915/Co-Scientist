"""Phase 2 on lit-tool-based generation: Validate novelty and refine/pivot.

This phase uses a two-stage approach:
1. Per-hypothesis per-paper novelty analysis (parallel)
2. Synthesis agent decides approve/refine/pivot based on analyses (with tool
access)

The helpers live in sibling modules (validate_search.py, validate_novelty.py,
validate_support.py, validate_synthesis.py, validate_stages.py); the two LLM
seams (call_llm_json
for the per-paper
novelty analysis and call_llm_with_tools for the synthesis agent) are called
from this module so tests can monkeypatch them on this namespace. The
stage-running functions built on top of those two seams
(_run_validate_novelty_stage, _run_validation_synthesis_stage, and their
supporting helpers) live in validate_stages.py, which reaches back into
this module's seam functions with a deferred, function-scoped import --
see that module's docstring for why. All helper names are re-exported
here for compatibility.
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
    _NoveltySearchContext as _NoveltySearchContext,
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
from co_scientist.agents.generation.literature_tools.validate_stages import (
    _count_validation_llm_calls as _count_validation_llm_calls,
)
from co_scientist.agents.generation.literature_tools.validate_stages import (
    _run_single_synthesis_call as _run_single_synthesis_call,
)
from co_scientist.agents.generation.literature_tools.validate_stages import (
    _run_synthesis_and_build_hypotheses as _run_synthesis_and_build_hypotheses,
)
from co_scientist.agents.generation.literature_tools.validate_stages import (
    _run_synthesis_stage_batches as _run_synthesis_stage_batches,
)
from co_scientist.agents.generation.literature_tools.validate_stages import (
    _run_validate_novelty_stage as _run_validate_novelty_stage,
)
from co_scientist.agents.generation.literature_tools.validate_stages import (
    _run_validation_synthesis_stage as _run_validation_synthesis_stage,
)
from co_scientist.agents.generation.literature_tools.validate_support import (
    _batch_hypotheses_for_synthesis as _batch_hypotheses_for_synthesis,
)
from co_scientist.agents.generation.literature_tools.validate_support import (
    _build_paper_metadata as _build_paper_metadata,
)
from co_scientist.agents.generation.literature_tools.validate_support import (
    _build_synthesis_context as _build_synthesis_context,
)
from co_scientist.agents.generation.literature_tools.validate_support import (
    _build_synthesis_prompt_metadata as _build_synthesis_prompt_metadata,
)
from co_scientist.agents.generation.literature_tools.validate_support import (
    _run_and_retry_synthesis_batches as _run_and_retry_synthesis_batches,
)
from co_scientist.agents.generation.literature_tools.validate_support import (
    _synthesis_tool_contract as _synthesis_tool_contract,
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
    _SynthesisCallInputs as _SynthesisCallInputs,
)
from co_scientist.agents.generation.literature_tools.validate_synthesis import (
    _SynthesisContext as _SynthesisContext,
)
from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    HIGH_TEMPERATURE,
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
    """Call the novelty-analysis LLM and return the structured analysis.

    Args:
        prompt: the per-paper novelty-analysis prompt.
        model_name: model to use for the novelty-analysis LLM call.

    Returns:
        The structured novelty-analysis result.
    """
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
    """Call the synthesis LLM with tools for one batch and return its result.

    Args:
        call_inputs: the assembled prompt and token budget for this batch.
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
        Tuple of (validated Hypothesis objects with novelty_validation,
        real LLM calls made across both stages -- finding L3).
    """
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
