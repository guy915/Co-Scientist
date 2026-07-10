"""Result assembly and completion reporting for the generation coordinator.

Routes gathered per-strategy task results into their buckets, applies the
degraded-mode literature_grounding fallback, and handles the summary logging
plus the generation-complete progress emission.
"""

import logging
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any

from co_scientist.constants import PROGRESS_GENERATE_COMPLETE
from co_scientist.models import Hypothesis
from co_scientist.nodes.generation.coordinator_strategy import GenerationCounts
from co_scientist.nodes.progress import emit_progress
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


@dataclass
class GenerationResults:
    """Encapsulates results from parallel generation execution."""

    tools_hypotheses: list[Hypothesis]
    debate_with_lit_hypotheses: list[Hypothesis]
    debate_only_hypotheses: list[Hypothesis]
    # One entry per debate run (both debate_with_lit and debate_only feed
    # this); tool-based generation has no transcript equivalent.
    debate_transcripts: list[dict[str, Any]]
    # Hypotheses from the iterative-assumptions technique (SSR §4); a plain
    # list like the tools path, with no transcript.
    assumptions_hypotheses: list[Hypothesis] = field(default_factory=list)

    @property
    def all_hypotheses(self) -> list[Hypothesis]:
        """All generated hypotheses across every strategy, in method order."""
        return (
            self.tools_hypotheses
            + self.debate_with_lit_hypotheses
            + self.debate_only_hypotheses
            + self.assumptions_hypotheses
        )


def _unpack_generation_results(
    tasks: list[tuple[str, Coroutine[Any, Any, Any]]],
    results: list[Any],
) -> GenerationResults:
    """Route gathered task results back into their per-strategy buckets.

    Args:
        tasks: the (task_type, coroutine) pairs passed to asyncio.gather, in
            the same order as results (task_type distinguishes the tools
            path's plain hypothesis list from the two debate paths'
            (hypotheses, transcripts) tuples).
        results: asyncio.gather's return value for those tasks.

    Returns:
        GenerationResults with each strategy's hypotheses/transcripts routed
        to the right field.
    """
    tools_hypotheses: list[Hypothesis] = []
    debate_with_lit_hypotheses: list[Hypothesis] = []
    debate_only_hypotheses: list[Hypothesis] = []
    assumptions_hypotheses: list[Hypothesis] = []
    debate_transcripts: list[dict[str, Any]] = []

    for i, (task_type, _) in enumerate(tasks):
        if task_type == "tools":
            tools_hypotheses = results[i]
        elif task_type == "debate_lit":
            debate_with_lit_hypotheses, transcripts = results[i]
            debate_transcripts.extend(transcripts)
        elif task_type == "debate_only":
            debate_only_hypotheses, transcripts = results[i]
            debate_transcripts.extend(transcripts)
        elif task_type == "assumptions":
            assumptions_hypotheses = results[i]

    return GenerationResults(
        tools_hypotheses=tools_hypotheses,
        debate_with_lit_hypotheses=debate_with_lit_hypotheses,
        debate_only_hypotheses=debate_only_hypotheses,
        debate_transcripts=debate_transcripts,
        assumptions_hypotheses=assumptions_hypotheses,
    )


def _apply_degraded_mode_fallback(hypotheses: list[Hypothesis]) -> None:
    """Sets a fallback literature_grounding message in degraded mode.

    Applies to every hypothesis generated without a literature review.
    """
    for hyp in hypotheses:
        # Always overwrite in non-lit-mcp mode to prevent hallucinated
        # citations: even if the model produced its own literature_grounding
        # text (it was told not to have literature), replace it so the
        # user-facing field never implies grounding that does not exist.
        hyp.literature_grounding = (
            "No literature review available. This hypothesis is based"
            " on the model's latent knowledge and has not been"
            " validated against current research literature."
            " Novelty and scientific validity should be independently"
            " verified."
        )


def _log_bucket_methods(label: str, hypotheses: list[Hypothesis]) -> None:
    """Log the generation_method of every hypothesis in one bucket.

    No-op when the bucket is empty.

    Args:
        label: name of the bucket, used as the log line prefix.
        hypotheses: hypotheses in this bucket.
    """
    if not hypotheses:
        return
    logger.debug(
        "%s generation_methods: %s",
        label,
        [
            h.generation_method.value if h.generation_method else None
            for h in hypotheses
        ],
    )


def _log_generation_summary(results: GenerationResults) -> None:
    """Log summary of generated hypotheses."""
    total = len(results.all_hypotheses)
    logger.info(
        "Generated %s total hypotheses (%s tool-based,"
        " %s debate-with-lit, %s debate-only)",
        total,
        len(results.tools_hypotheses),
        len(results.debate_with_lit_hypotheses),
        len(results.debate_only_hypotheses),
    )

    _log_bucket_methods("tool-based", results.tools_hypotheses)
    _log_bucket_methods("debate-with-Lit", results.debate_with_lit_hypotheses)
    _log_bucket_methods("debate-only", results.debate_only_hypotheses)


def _build_summary_message_parts(
    results: GenerationResults, counts: GenerationCounts
) -> list[str]:
    """Build message parts for summary output."""
    parts = []
    if counts.tools_count > 0:
        parts.append(f"{len(results.tools_hypotheses)} tool-based")
    if counts.debate_with_lit_count > 0:
        parts.append(
            f"{len(results.debate_with_lit_hypotheses)} debate-with-literature"
        )
    if counts.debate_only_count > 0:
        parts.append(f"{len(results.debate_only_hypotheses)} debate-only")
    if counts.assumptions_count > 0:
        parts.append(f"{len(results.assumptions_hypotheses)} assumptions")
    return parts


async def _emit_complete_progress(
    state: WorkflowState, results: GenerationResults, counts: GenerationCounts
) -> str:
    """Emit progress callback for generation complete.

    Returns:
        The human-readable generation summary message that was emitted.
    """
    parts = _build_summary_message_parts(results, counts)
    all_hypotheses = results.all_hypotheses

    message = f"Generated {len(all_hypotheses)} hypotheses ({', '.join(parts)})"

    await emit_progress(
        state,
        "generation_complete",
        message,
        PROGRESS_GENERATE_COMPLETE,
        hypotheses_count=len(all_hypotheses),
    )
    return message
