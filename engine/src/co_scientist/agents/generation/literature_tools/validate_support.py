"""Batching and context assembly for the validation synthesis stage.

Non-LLM helpers for Phase 2 validation: paper/prompt metadata payloads,
splitting Stage 1 output into synthesis batches, the batch run-and-retry
orchestration, and shared synthesis-context construction. The LLM seams
themselves stay in validate.py so tests can monkeypatch them there.
"""

import dataclasses
import logging
from typing import TYPE_CHECKING, Any, Optional

from co_scientist.agents.generation.literature_tools.validate_synthesis import (
    _retry_failed_synthesis_batches,
    _run_synthesis_batches,
    _setup_validation_tool_provider,
    _SynthesisCaller,
    _SynthesisContext,
)
from co_scientist.constants import VALIDATION_SYNTHESIS_BATCH_SIZE
from co_scientist.state import WorkflowState

if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry

logger = logging.getLogger(__name__)


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


def _synthesis_tool_contract(
    tool_registry: Optional["ToolRegistry"],
) -> dict[str, Any] | None:
    """Resolve the tool registry's config as a cache-key-able contract.

    The synthesis agent's tool *schema* (names/descriptions/params) is
    already part of the LLM cache key via ``ToolLoop.tools``; this instead
    captures what those tools actually do -- which sources are enabled,
    their endpoints and parameter mappings -- so a registry change that
    leaves the schema untouched still invalidates a cached transcript.
    Mirrors ``agents/generation/literature_review/node.py``'s
    ``_literature_cache_params`` tool_contract.

    Returns:
        The registry config as a plain dict, or None with no registry.
    """
    if tool_registry is None:
        return None
    return dataclasses.asdict(tool_registry.config)


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


def _build_synthesis_context(
    hypotheses_with_analyses: list[dict[str, Any]],
    state: WorkflowState,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    reference_index: Any | None,
) -> _SynthesisContext:
    """Resolve the tool provider and assemble the shared synthesis context.

    The research goal is read from state; everything else is threaded in.

    Args:
        hypotheses_with_analyses: Stage 1 output, sized for iteration budget.
        state: current workflow state.
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
        state["research_goal"],
        max_iterations,
        tool_registry,
        reference_index,
        provider,
        openai_tools,
    )
