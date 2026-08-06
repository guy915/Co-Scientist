"""Result assembly and completion reporting for the generation coordinator.

Routes gathered per-strategy task results into their buckets, applies the
degraded-mode literature_grounding fallback, and handles the summary logging
plus the generation-complete progress emission.
"""

import logging
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any

from co_scientist.agents.generation.coordinator_strategy import (
    GenerationCounts,
)
from co_scientist.constants import PROGRESS_GENERATE_COMPLETE
from co_scientist.models import Hypothesis
from co_scientist.progress import emit_progress
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
    # Real LLM calls spent across every strategy that ran this cycle
    # (finding L3 -- generation previously reported none at all).
    llm_call_count: int = 0

    @property
    def all_hypotheses(self) -> list[Hypothesis]:
        """All generated hypotheses across every strategy, in method order."""
        return (
            self.tools_hypotheses
            + self.debate_with_lit_hypotheses
            + self.debate_only_hypotheses
            + self.assumptions_hypotheses
        )


_DEBATE_TASK_TYPES = ("debate_lit", "debate_only")


def _route_one_task_result(
    task_type: str,
    result: Any,
    buckets: dict[str, list[Hypothesis]],
    debate_transcripts: list[dict[str, Any]],
) -> int:
    """Route one gathered task result into its bucket, mutating in place.

    Every strategy's coroutine returns its hypotheses paired with the real
    LLM-call count it spent (see generate_with_debate / _with_assumptions /
    _with_tools -- finding L3); a debate task's result additionally carries
    its per-debate transcripts as a middle element, unlike the
    tools/assumptions tasks' plain (hypotheses, llm_calls) pairs.

    Returns:
        The LLM-call count this task reported.
    """
    if task_type in _DEBATE_TASK_TYPES:
        hypotheses, transcripts, llm_calls = result
        buckets[task_type] = hypotheses
        debate_transcripts.extend(transcripts)
    else:
        hypotheses, llm_calls = result
        buckets[task_type] = hypotheses
    return int(llm_calls)


def _unpack_generation_results(
    tasks: list[tuple[str, Coroutine[Any, Any, Any]]],
    results: list[Any],
) -> GenerationResults:
    """Route gathered task results back into their per-strategy buckets.

    Args:
        tasks: the (task_type, coroutine) pairs passed to asyncio.gather, in
            the same order as results (task_type distinguishes the tools/
            assumptions paths' (hypotheses, llm_calls) pairs from the two
            debate paths' (hypotheses, transcripts, llm_calls) triples).
        results: asyncio.gather's return value for those tasks.

    Returns:
        GenerationResults with each strategy's hypotheses/transcripts
        routed to the right field, and llm_call_count summed across all of
        them.
    """
    buckets: dict[str, list[Hypothesis]] = {
        "tools": [],
        "debate_lit": [],
        "debate_only": [],
        "assumptions": [],
    }
    debate_transcripts: list[dict[str, Any]] = []

    llm_call_count = 0
    for i, (task_type, _) in enumerate(tasks):
        llm_call_count += _route_one_task_result(
            task_type, results[i], buckets, debate_transcripts
        )

    return GenerationResults(
        tools_hypotheses=buckets["tools"],
        debate_with_lit_hypotheses=buckets["debate_lit"],
        debate_only_hypotheses=buckets["debate_only"],
        debate_transcripts=debate_transcripts,
        assumptions_hypotheses=buckets["assumptions"],
        llm_call_count=llm_call_count,
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
    """Log summary of generated hypotheses.

    The breakdown covers every bucket that feeds all_hypotheses. Assumptions
    was left out of it while still being counted in the total, so any run
    allocating an assumptions slice (total_count >= 4) logged parts that did
    not sum to the total it printed.
    """
    total = len(results.all_hypotheses)
    logger.info(
        "Generated %s total hypotheses (%s tool-based,"
        " %s debate-with-lit, %s debate-only, %s assumptions)",
        total,
        len(results.tools_hypotheses),
        len(results.debate_with_lit_hypotheses),
        len(results.debate_only_hypotheses),
        len(results.assumptions_hypotheses),
    )

    _log_bucket_methods("tool-based", results.tools_hypotheses)
    _log_bucket_methods("debate-with-Lit", results.debate_with_lit_hypotheses)
    _log_bucket_methods("debate-only", results.debate_only_hypotheses)
    _log_bucket_methods("assumptions", results.assumptions_hypotheses)


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
