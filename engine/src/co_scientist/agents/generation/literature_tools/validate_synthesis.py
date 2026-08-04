"""Stage 2 synthesis helpers for the tool-based validation phase.

Holds the tool-provider setup, prompt/token-budget assembly, batch
execution with per-hypothesis retry, response parsing, and final Hypothesis
assembly for the validation synthesis stage. The single LLM synthesis call
itself lives in validate.py so its ``call_llm_with_tools`` seam stays
monkeypatchable on the validate module namespace.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NamedTuple, Optional

from co_scientist.agents.generation.citations import (
    hypothesis_from_llm_output,
)
from co_scientist.agents.generation.literature_tools.draft import (
    _setup_tool_provider,
)
from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    VALIDATION_SYNTHESIS_MAX_TOKENS_CAP,
    VALIDATION_SYNTHESIS_TOKENS_PER_HYPOTHESIS,
    get_validate_max_iterations,
    scaled_max_tokens,
)
from co_scientist.llm_json import parse_tool_loop_json
from co_scientist.models import GenerationMethod, Hypothesis
from co_scientist.prompts import (
    ValidationSynthesisRequest,
    get_validation_synthesis_prompt_with_tools,
)
from co_scientist.state import WorkflowState
from co_scientist.tools.provider import MCPToolProvider

if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry

logger = logging.getLogger(__name__)

# Type of the nested `_call_synthesis` closure defined inside
# _run_synthesis_stage_batches in validate.py (it closes over a
# _SynthesisContext); threading it through as a plain callable lets the
# batch-execution/retry helpers below stay free of that closure state.
_SynthesisCaller = Callable[
    [list[dict[str, Any]], str, list[str] | None],
    Awaitable[list[dict[str, Any]]],
]


class _SynthesisContext(NamedTuple):
    """Per-call state shared by every synthesis batch/retry invocation.

    Bundles the locals _run_single_synthesis_call needs beyond its own
    batch/batch_label/already_validated_texts arguments, so callers thread
    one object instead of seven positional locals.
    """

    state: WorkflowState
    research_goal: str
    max_iterations: int
    tool_registry: Optional["ToolRegistry"]
    reference_index: Any | None
    provider: MCPToolProvider
    openai_tools: list[Any]


class _SynthesisCallInputs(NamedTuple):
    """Prompt and token budget assembled for one synthesis batch call."""

    prompt: str
    max_tokens: int


@dataclass(frozen=True)
class _SynthesisRetryState:
    """Accumulators and caller shared across individual synthesis retries.

    Attributes:
        all_validated_hypotheses: Validated hypothesis dicts accumulated so
            far; successful retries are appended here in place.
        accumulated_texts: Hypothesis texts validated so far; extended in
            place so subsequent retries in the same pass see this context.
        call_synthesis: The synthesis callable to invoke per hypothesis.
    """

    all_validated_hypotheses: list[dict[str, Any]]
    accumulated_texts: list[str]
    call_synthesis: _SynthesisCaller


def _setup_validation_tool_provider(
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    total_hypotheses: int,
) -> tuple[MCPToolProvider, list[Any], Optional["ToolRegistry"], int]:
    """Resolve the tool registry/whitelist and init the synthesis provider.

    Also computes the per-call synthesis iteration budget, since it is
    sized from the same total_hypotheses count.

    Args:
        mcp_client: MCP client for tool access.
        tool_registry: optional ToolRegistry for config-driven tool
            selection; resolved from the global registry when None.
        total_hypotheses: total draft count, used to size the iteration
            budget.

    Returns:
        Tuple of (provider, openai_tools, resolved tool_registry,
        max_iterations).
    """
    provider, openai_tools, tool_registry = _setup_tool_provider(
        mcp_client, tool_registry, "validation", "validation", logger
    )

    # Calculate iteration budget for synthesis
    # Sized from the TOTAL hypothesis count but applied per synthesis call,
    # so each batch (and each single-hypothesis retry) gets the full budget.
    max_iterations = get_validate_max_iterations(total_hypotheses)
    logger.info("Validation synthesis budget: %s iterations", max_iterations)

    return provider, openai_tools, tool_registry, max_iterations


def _compute_synthesis_max_tokens(
    batch: list[dict[str, Any]], batch_label: str
) -> int:
    """Scale and log the synthesis call's max-token budget for one batch.

    Args:
        batch: hypothesis batch (with novelty analyses) to synthesize.
        batch_label: label identifying this batch, used in logging.

    Returns:
        The scaled max-tokens budget for this batch's synthesis call.
    """
    synthesis_max_tokens = scaled_max_tokens(
        EXTENDED_MAX_TOKENS,
        len(batch),
        per_item=VALIDATION_SYNTHESIS_TOKENS_PER_HYPOTHESIS,
        cap=VALIDATION_SYNTHESIS_MAX_TOKENS_CAP,
    )
    logger.debug(
        "Batch %s token budget: %s for %s hypotheses",
        batch_label,
        synthesis_max_tokens,
        len(batch),
    )
    return synthesis_max_tokens


def _build_synthesis_call_inputs(
    batch: list[dict[str, Any]],
    batch_label: str,
    already_validated_texts: list[str] | None,
    ctx: _SynthesisContext,
) -> _SynthesisCallInputs:
    """Build the synthesis prompt and its token budget for one batch.

    Args:
        batch: hypothesis batch (with novelty analyses) to synthesize.
        batch_label: label identifying this batch, used in logging.
        already_validated_texts: hypothesis texts already validated in
            prior batches/retries, or None.
        ctx: shared per-call synthesis state.

    Returns:
        The (prompt, max_tokens) inputs for this batch's synthesis call.
    """
    ref_text = ctx.reference_index.text if ctx.reference_index else ""
    synthesis_prompt, _ = get_validation_synthesis_prompt_with_tools(
        ValidationSynthesisRequest(
            research_goal=ctx.research_goal,
            hypotheses_with_analyses=batch,
            articles=ctx.state.get("articles"),
            articles_with_reasoning=ctx.state.get("articles_with_reasoning"),
            max_iterations=ctx.max_iterations,
            tool_registry=ctx.tool_registry,
            reference_list=ref_text,
            already_validated_texts=already_validated_texts,
        )
    )

    synthesis_max_tokens = _compute_synthesis_max_tokens(batch, batch_label)

    return _SynthesisCallInputs(synthesis_prompt, synthesis_max_tokens)


def _log_synthesis_tool_call_summary(
    batch_label: str,
    tool_call_counts: dict[str, int],
) -> None:
    """Log the total/per-tool call counts for one synthesis batch, if any.

    Args:
        batch_label: label identifying this batch, used in logging.
        tool_call_counts: per-tool-name call counts from the tracked
            executor.
    """
    total_calls = sum(tool_call_counts.values())
    if total_calls > 0:
        calls_summary = ", ".join(
            f"{n}={c}" for n, c in tool_call_counts.items()
        )
        logger.info(
            "Batch %s: %s tool calls (%s)",
            batch_label,
            total_calls,
            calls_summary,
        )


def _parse_synthesis_response(
    final_response: str, batch_label: str
) -> list[dict[str, Any]]:
    """Parse one synthesis batch's final LLM response into hypothesis dicts.

    Args:
        final_response: the synthesis agent's final tool-call-loop response.
        batch_label: label identifying this batch, used in errors/logging.

    Returns:
        The parsed "hypotheses" list from the response.

    Raises:
        ResponseParseError: if the response cannot be parsed as JSON even
            after repair attempts.
    """
    result: list[dict[str, Any]] = parse_tool_loop_json(
        final_response,
        "hypotheses",
        f"Validation synthesis (batch {batch_label})",
    )
    logger.debug(
        "Batch %s synthesis returned %s hypotheses", batch_label, len(result)
    )
    return result


def _partition_synthesis_results(
    batches: list[list[dict[str, Any]]],
    raw_results: list[list[dict[str, Any]] | BaseException],
) -> tuple[list[dict[str, Any]], list[tuple[int, list[dict[str, Any]]]]]:
    """Split gathered synthesis results into validated hypotheses vs failures.

    Args:
        batches: the hypothesis batches the results correspond to.
        raw_results: per-batch results or exceptions from
            asyncio.gather(return_exceptions=True).

    Returns:
        Tuple of (validated hypothesis dicts from batches that succeeded,
        list of (batch_index, batch) pairs for batches that raised).
    """
    all_validated_hypotheses: list[dict[str, Any]] = []
    failed_batches: list[tuple[int, list[dict[str, Any]]]] = []

    for i, result in enumerate(raw_results):
        if isinstance(result, Exception):
            logger.warning(
                "Batch %s failed (%s); will retry hypotheses individually",
                i + 1,
                result,
            )
            failed_batches.append((i, batches[i]))
        else:
            # gather(return_exceptions=True) types results as possibly
            # BaseException; the isinstance branch above already filtered
            # those out, which mypy cannot narrow across the if/else.
            all_validated_hypotheses.extend(result)  # type: ignore[arg-type]

    return all_validated_hypotheses, failed_batches


async def _run_synthesis_batches(
    batches: list[list[dict[str, Any]]],
    call_synthesis: _SynthesisCaller,
) -> tuple[list[dict[str, Any]], list[tuple[int, list[dict[str, Any]]]]]:
    """Run every batch's synthesis call in parallel, isolating failures.

    Args:
        batches: hypothesis batches to run synthesis over.
        call_synthesis: the (batch, batch_label, already_validated_texts)
            synthesis callable to invoke for each batch.

    Returns:
        Tuple of (validated hypothesis dicts from batches that succeeded,
        list of (batch_index, batch) pairs for batches that raised).
    """
    # return_exceptions=True: one batch's exception must not cancel or
    # abort the other batches running concurrently in this gather.
    raw_results = await asyncio.gather(
        *[
            call_synthesis(batch, str(i + 1), None)
            for i, batch in enumerate(batches)
        ],
        return_exceptions=True,
    )

    all_validated_hypotheses, failed_batches = _partition_synthesis_results(
        batches, raw_results
    )
    logger.info(
        "%s/%s batches succeeded, %s need individual retry",
        len(batches) - len(failed_batches),
        len(batches),
        len(failed_batches),
    )

    return all_validated_hypotheses, failed_batches


def _accumulate_retry_result(
    single_result: list[dict[str, Any]],
    all_validated_hypotheses: list[dict[str, Any]],
    accumulated_texts: list[str],
) -> None:
    """Merge one successful individual retry into the shared accumulators.

    Args:
        single_result: the validated hypothesis dict(s) from one retry.
        all_validated_hypotheses: validated hypothesis dicts accumulated so
            far; extended in place.
        accumulated_texts: hypothesis texts validated so far; extended in
            place so subsequent retries in the same pass see this context.
    """
    all_validated_hypotheses.extend(single_result)
    for h in single_result:
        text = h.get("hypothesis", "")
        if text:
            accumulated_texts.append(text)


async def _retry_one_hypothesis(
    batch_idx: int,
    hyp_idx: int,
    hyp_data: dict[str, Any],
    retry_state: _SynthesisRetryState,
) -> None:
    """Retry a single hypothesis from a failed batch, best-effort.

    A hypothesis whose individual retry also fails is dropped; the run
    continues with whatever validated.

    Args:
        batch_idx: 0-based index of the failed batch, used in the retry
            label and error logging.
        hyp_idx: 0-based index of this hypothesis within its failed batch.
        hyp_data: the hypothesis dict to retry.
        retry_state: shared retry accumulators and synthesis callable;
            its lists are extended in place on success.
    """
    label = f"{batch_idx + 1}_retry_{hyp_idx + 1}"
    accumulated_texts = retry_state.accumulated_texts
    context = accumulated_texts if accumulated_texts else None
    try:
        single_result = await retry_state.call_synthesis(
            [hyp_data], label, context
        )
    except Exception as e:
        logger.error(
            "Individual retry failed for batch %s, hypothesis %s: %s",
            batch_idx + 1,
            hyp_idx + 1,
            e,
        )
        return

    _accumulate_retry_result(
        single_result,
        retry_state.all_validated_hypotheses,
        accumulated_texts,
    )


async def _retry_failed_synthesis_batches(
    failed_batches: list[tuple[int, list[dict[str, Any]]]],
    all_validated_hypotheses: list[dict[str, Any]],
    call_synthesis: _SynthesisCaller,
) -> None:
    """Retry each hypothesis from the failed batches one at a time.

    Single-hypothesis calls shrink the blast radius: one bad hypothesis or
    truncated output no longer sinks its batch-mates.

    Args:
        failed_batches: (batch_index, batch) pairs that failed as a whole
            batch.
        all_validated_hypotheses: validated hypothesis dicts accumulated so
            far; successful retries are appended here in place.
        call_synthesis: the synthesis callable to invoke per hypothesis.
    """
    retry_state = _SynthesisRetryState(
        all_validated_hypotheses=all_validated_hypotheses,
        # Seed context with texts from successful batches
        accumulated_texts=[
            h.get("hypothesis", "")
            for h in all_validated_hypotheses
            if h.get("hypothesis")
        ],
        call_synthesis=call_synthesis,
    )

    for batch_idx, failed_batch in failed_batches:
        for hyp_idx, hyp_data in enumerate(failed_batch):
            await _retry_one_hypothesis(
                batch_idx, hyp_idx, hyp_data, retry_state
            )


def _build_hypotheses_from_synthesis(
    all_validated_hypotheses: list[dict[str, Any]],
    reference_index: Any | None,
) -> list[Hypothesis]:
    """Build Hypothesis objects from the synthesis stage's raw output.

    Output order matches hypotheses_with_analyses order (batched
    sequentially).

    Args:
        all_validated_hypotheses: raw hypothesis dicts from synthesis.
        reference_index: optional citation reference index supplying the
            source map for citation-key resolution.

    Returns:
        List of Hypothesis objects tagged GenerationMethod.LITERATURE_TOOLS.
    """
    ref_sources = reference_index.sources if reference_index else {}
    hypotheses = []
    for hyp_data in all_validated_hypotheses:
        # novelty_validation is this generation path's caller-specific
        # extra field, threaded through hypothesis_from_llm_output's
        # **extra (shared constructor also used by debate.py).
        hypothesis = hypothesis_from_llm_output(
            hyp_data,
            ref_sources,
            GenerationMethod.LITERATURE_TOOLS,
            novelty_validation=hyp_data.get("novelty_validation"),
        )
        hypotheses.append(hypothesis)
    return hypotheses
