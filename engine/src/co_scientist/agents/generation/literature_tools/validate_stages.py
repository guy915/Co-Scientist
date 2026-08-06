"""Stage-running orchestration for Phase 2 novelty validation.

``validate_hypotheses`` (in ``validate.py``) runs two stages: Stage 1
per-paper novelty analysis and Stage 2 synthesis-with-retries. This
module holds the functions that drive both stages end to end --
batching, retrying, and assembling the final ``Hypothesis`` list --
while the two functions that actually invoke the model
(``_call_novelty_analysis_llm``/``_analyze_paper_novelty`` for Stage 1's
``call_llm_json``, and ``_invoke_synthesis_llm`` for Stage 2's
``call_llm_with_tools``) stay behind in ``validate.py``, because tests
monkeypatch those two LLM calls on ``validate.py``'s own namespace (see
its module docstring).

``_run_single_synthesis_call`` and ``_run_validate_novelty_stage`` --
the two functions here that reach back into one of those seams -- import
it locally, inside the function body, rather than at module load time.
A top-level import here would cycle with ``validate.py`` (which imports
this module to re-export every name defined here): each module would
need a name from the other before either had finished executing its own
body, and Python cannot resolve that. The deferred import runs well
after both modules are fully loaded, so it always resolves the current
(possibly test-patched) function.
"""

import logging
from typing import TYPE_CHECKING, Any, Optional

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
from co_scientist.agents.generation.literature_tools.validate_synthesis import (
    _build_hypotheses_from_synthesis,
    _build_synthesis_call_inputs,
    _log_synthesis_tool_call_summary,
    _parse_synthesis_response,
    _SynthesisContext,
)
from co_scientist.constants import corpus_slug
from co_scientist.models import Hypothesis
from co_scientist.state import WorkflowState

if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry

logger = logging.getLogger(__name__)


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
    # Imported here, not at module load time -- see the module docstring
    # for why a top-level import would cycle with validate.py.
    from co_scientist.agents.generation.literature_tools.validate import (
        _invoke_synthesis_llm,
    )

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


async def _run_validation_synthesis_stage(
    hypotheses_with_analyses: list[dict[str, Any]],
    state: WorkflowState,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    reference_index: Any | None,
) -> list[dict[str, Any]]:
    """Run Stage 2: synthesize approve/refine/pivot decisions for all drafts.

    The synthesis agent has tool access for searching additional papers
    when pivoting. The research goal is read from state.

    Args:
        hypotheses_with_analyses: Stage 1 output, one dict per draft with
            "draft" and "novelty_analyses" keys.
        state: current workflow state.
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
    """Derive the shared corpus slug and run Stage 1 novelty analysis.

    Args:
        draft_hypotheses: list of draft dicts from Phase 1.
        state: current workflow state.
        mcp_client: MCP client for tool access.
        tool_registry: optional ToolRegistry for config-driven tool
            selection.

    Returns:
        Stage 1 output, one dict per draft with "draft" and
        "novelty_analyses" keys.
    """
    # Imported here, not at module load time -- see the module docstring
    # for why a top-level import would cycle with validate.py.
    from co_scientist.agents.generation.literature_tools.validate import (
        _analyze_paper_novelty,
    )

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
    """Run Stage 2 synthesis and build the final validated Hypothesis list.

    Args:
        hypotheses_with_analyses: Stage 1 output, one dict per draft.
        state: current workflow state.
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
    """Count real LLM calls Stage 1 + Stage 2 spent validating drafts.

    Stage 1 issues exactly one ``call_llm_json`` per successfully-analyzed
    paper (failures are filtered out by ``_gather_novelty_analyses``, so
    this undercounts by any failed attempt -- the same convention
    ``ranking``/``evolve`` use elsewhere for a call count that is real but
    not exhaustive). Stage 2 issues one ``call_llm_with_tools`` per
    synthesis batch; a batch that later needs an individual retry
    (``_retry_failed_synthesis_batches``) spends more calls than counted
    here, so this is a floor, not an exact total.

    Args:
        hypotheses_with_analyses: Stage 1 output, one dict per draft.

    Returns:
        The approximate real LLM-call count for both stages (finding L3).
    """
    novelty_calls = sum(
        len(item.get("novelty_analyses") or [])
        for item in hypotheses_with_analyses
    )
    synthesis_calls = len(
        _batch_hypotheses_for_synthesis(hypotheses_with_analyses)
    )
    return novelty_calls + synthesis_calls
