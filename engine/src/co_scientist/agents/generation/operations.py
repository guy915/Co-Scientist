"""Generation planning and finalization shared by graph and durable callers.

These operations validate and allocate a cycle, then turn its successful
strategy results into an append update. They do not schedule or execute
strategies, commit state, or decide failure isolation. Preparation buys no
research: graph-only expansion remains in the coordinator, so calling this
boundary from a durable planner does not change its retrieval or spend.
Finalization can run configured enrichment tools and must precede any store
transaction.
"""

import logging
from collections import Counter
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any

from co_scientist.agents.generation.citations import (
    ReferenceIndex,
    build_reference_index,
)
from co_scientist.agents.generation.coordinator_enrichment import (
    _enrich_hypotheses,
)
from co_scientist.agents.generation.coordinator_strategy import (
    GenerationCounts,
    _check_literature_availability,
    _determine_generation_counts,
    _report_generation_start,
)
from co_scientist.agents.meta_review.interim_overview import (
    format_interim_overview,
)
from co_scientist.constants import PROGRESS_GENERATE_COMPLETE
from co_scientist.exceptions import GenerationError
from co_scientist.models import GenerationMethod, Hypothesis
from co_scientist.progress import emit_progress
from co_scientist.state import AppendHypotheses, WorkflowState

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


def _unpack_generation_results(
    tasks: list[tuple[str, Coroutine[Any, Any, Any]]],
    results: list[Any],
) -> GenerationResults:
    """Collect ordered strategy results and real provider-call counts."""
    buckets: dict[str, list[Hypothesis]] = {
        "tools": [],
        "debate_lit": [],
        "debate_only": [],
        "assumptions": [],
    }
    debate_transcripts: list[dict[str, Any]] = []
    llm_call_count = 0
    for (kind, _), result in zip(tasks, results, strict=True):
        if kind in ("debate_lit", "debate_only"):
            hypotheses, transcripts, llm_calls = result
            debate_transcripts.extend(transcripts)
        else:
            hypotheses, llm_calls = result
        buckets[kind] = hypotheses
        llm_call_count += int(llm_calls)
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


async def _emit_complete_progress(
    state: WorkflowState, results: GenerationResults, counts: GenerationCounts
) -> str:
    """Emit progress callback for generation complete.

    Returns:
        The human-readable generation summary message that was emitted.
    """
    parts = [
        f"{len(hypotheses)} {label}"
        for count, hypotheses, label in (
            (counts.tools_count, results.tools_hypotheses, "tool-based"),
            (
                counts.debate_with_lit_count,
                results.debate_with_lit_hypotheses,
                "debate-with-literature",
            ),
            (
                counts.debate_only_count,
                results.debate_only_hypotheses,
                "debate-only",
            ),
            (
                counts.assumptions_count,
                results.assumptions_hypotheses,
                "assumptions",
            ),
        )
        if count > 0
    ]
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


@dataclass(frozen=True)
class GenerationPlan:
    """Resolved allocation and shared inputs for one generation cycle.

    Attributes:
        counts: Hypothesis allocation per method, including mode flags.
        reference_index: Shared citation keys across the enabled strategies.
        literature: Literature context, with any interim overview prepended.
            Debate-only callers must explicitly omit this context.
    """

    counts: GenerationCounts
    reference_index: ReferenceIndex
    literature: str | None


def _log_reference_index_summary(reference_index: ReferenceIndex) -> None:
    """Log a paper/KG-source breakdown of a non-empty reference index."""
    if reference_index.is_empty():
        return
    # Keys are uniformly "C<n>"; the paper/KG split lives in each source's
    # "type" field (see build_reference_index).
    counts = Counter(s.get("type") for s in reference_index.sources.values())
    logger.info(
        "Built reference index: %s paper(s), %s KG source(s)",
        counts["paper"],
        counts["knowledge_graph"],
    )


async def prepare_generation(
    state: WorkflowState,
) -> GenerationPlan:
    """Validate preconditions and resolve strategy, counts, and references.

    Also logs the resolved strategy and emits the generation-start progress
    callback, since both key off the counts computed here.

    Returns:
        The allocation, shared citation namespace, and strategy context.

    Raises:
        GenerationError: if supervisor_guidance is missing from state.
    """
    if not state.get("supervisor_guidance"):
        raise GenerationError(
            "No supervisor_guidance in state for node=generation"
        )
    articles_with_reasoning = state.get("articles_with_reasoning")
    total_count = state["initial_hypotheses_count"]
    has_literature = _check_literature_availability(
        articles_with_reasoning, bool(state.get("mcp_available", False))
    )
    counts = _determine_generation_counts(
        state,
        total_count,
        has_literature,
        bool(state.get("enable_tool_calling_generation", False)),
    )

    # Shared [C*] citation-key namespace for every strategy below.
    reference_index = build_reference_index(
        articles=state.get("articles"),
        context_enrichment_sources=state.get("context_enrichment_sources"),
    )
    _log_reference_index_summary(reference_index)

    await _report_generation_start(state, counts, total_count)

    return GenerationPlan(
        counts=counts,
        reference_index=reference_index,
        literature=_with_interim_overview(state, articles_with_reasoning),
    )


def _with_interim_overview(
    state: WorkflowState, articles_with_reasoning: str | None
) -> str | None:
    """Prepend interim guidance without treating it as retrieved literature.

    Availability is checked before this step. Debate-only calls explicitly
    omit this context, so a run's own synthesis cannot imply grounding.
    """
    block = format_interim_overview(state)
    if not block:
        return articles_with_reasoning
    if not articles_with_reasoning:
        return block
    return f"{block}\n\n{articles_with_reasoning}"


def _stamp_generation_lineage(
    hypotheses: list[Hypothesis], creation_iteration: int
) -> None:
    """Stamp generation-0 lineage and research-expansion provenance in place.

    origin/generation keep their construction defaults (GENERATION, 0); the
    Generation agent produces roots, so parent_id stays None. Later
    research-expansion cycles reuse this node with a higher iteration, in
    which case the underlying generation method is preserved as provenance
    before the observable technique is stamped over it.

    Args:
        hypotheses: hypotheses to stamp, mutated in place.
        creation_iteration: workflow iteration that produced these
            hypotheses.
    """
    for hyp in hypotheses:
        hyp.creation_iteration = creation_iteration
        if creation_iteration > 0:
            if hyp.generation_method is not None:
                hyp.enrichments["base_generation_method"] = (
                    hyp.generation_method.value
                )
            hyp.generation_method = GenerationMethod.RESEARCH_EXPANSION


async def finalize_generation(
    state: WorkflowState,
    counts: GenerationCounts,
    results: GenerationResults,
) -> dict[str, Any]:
    """Apply the degraded-mode fallback, enrich, and build the result dict.

    Args:
        state: current workflow state
        counts: Per-strategy counts from preparation.
        results: Gathered strategy results.

    Returns:
        dict with hypotheses, debate_transcripts, hypothesis_count,
        llm_call_count, message.
    """
    # Only debate_only_hypotheses need the fallback message: tools_ and
    # debate_with_lit_hypotheses are only populated when has_literature was
    # true, so is_degraded_mode and those lists are mutually exclusive by
    # construction. Assumptions generation runs in the same no-literature
    # path, so its hypotheses need the same fallback grounding.
    if counts.is_degraded_mode:
        _apply_degraded_mode_fallback(results.debate_only_hypotheses)
        _apply_degraded_mode_fallback(results.assumptions_hypotheses)

    _log_generation_summary(results)
    message_content = await _emit_complete_progress(state, results, counts)

    all_hypotheses = results.all_hypotheses
    _stamp_generation_lineage(all_hypotheses, state.get("current_iteration", 0))

    # Run post-generation enrichments (e.g., NVD CVE lookup)
    await _enrich_hypotheses(all_hypotheses, state)

    # Append (not replace): a later generation cycle adds to the pool.
    return {
        "hypotheses": AppendHypotheses(all_hypotheses),
        "debate_transcripts": results.debate_transcripts,
        "hypothesis_count": len(all_hypotheses),
        "llm_call_count": results.llm_call_count,
        "message": message_content,
    }
