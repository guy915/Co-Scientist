"""Proximity node - cluster and deduplicate similar hypotheses."""

import logging
import time
from dataclasses import dataclass
from typing import Any

from co_scientist.agents.proximity.proximity_dedup import (
    _assign_cluster_ids,
    _dedupe_by_cluster,
)
from co_scientist.agents.proximity.proximity_graph import (
    SurvivorIndex,
    build_proximity_graph,
    member_match_key,
)
from co_scientist.constants import (
    LONG_MAX_TOKENS,
    LOW_TEMPERATURE,
    PROGRESS_PROXIMITY_COMPLETE,
    PROGRESS_PROXIMITY_START,
)
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm_json,
)
from co_scientist.models import (
    Hypothesis,
    MetricDeltas,
    create_metrics_update,
    phase_message,
)
from co_scientist.progress import emit_progress
from co_scientist.prompts import get_proximity_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


def _prepare_hypotheses_for_analysis(
    hypotheses: list[Hypothesis],
) -> list[dict[str, Any]]:
    """Builds the per-hypothesis payload sent to the proximity LLM call.

    Sends only the fields the clustering prompt needs, plus the positional
    `index` a response names its cluster members by. That index is how both
    deduplication (_assign_cluster_ids) and the persisted proximity graph
    (_survivor_index) resolve a member back to its Hypothesis, with echoed
    text kept only as a fallback.

    Text is sent whole, deliberately. This is the only node that puts the
    entire pool in one prompt, so it is the obvious place to economise by
    truncating -- and the wrong one. Three of the six dimensions the prompt
    weighs (methodology, assumptions, applications) are argued in a
    hypothesis's tail, so a head-only payload hides exactly the differences
    that separate two neighbours, and this node's verdict deletes work:
    a false "high" drops a hypothesis that was actually distinct, silently.
    The saving was never worth it either -- the pool costs a few thousand
    input tokens against a call whose spend is dominated by reasoning
    output, which is where the budget failures here have always come from
    (see THINKING_FLOOR_MAX_TOKENS). Fix an over-long prompt by chunking the
    pool, never by narrowing what each comparison gets to see.

    Args:
        hypotheses: All hypotheses being analyzed for proximity.

    Returns:
        Per-hypothesis dicts for the proximity prompt.
    """
    return [
        {
            "text": hyp.text,
            "score": hyp.score,
            "elo_rating": hyp.elo_rating,
            "index": i,
        }
        for i, hyp in enumerate(hypotheses)
    ]


async def _call_proximity_llm(
    state: WorkflowState,
    prompt: str,
    schema: dict[str, Any] | None,
    hypotheses_count: int,
) -> dict[str, Any]:
    """Calls the proximity LLM and returns its parsed JSON response."""
    return await call_llm_json(
        prompt=prompt,
        spec=CompletionSpec(
            model_name=state["model_name"],
            max_tokens=LONG_MAX_TOKENS,
            temperature=LOW_TEMPERATURE,
            json_schema=schema,
        ),
        options=LLMCallOptions(
            run_id=state.get("run_id"),
            prompt_name="proximity",
            prompt_metadata={
                "prompt_length_chars": len(prompt),
                "hypotheses_count": hypotheses_count,
            },
        ),
    )


async def _fetch_similarity_clusters(
    state: WorkflowState, hypotheses: list[Hypothesis]
) -> list[dict[str, Any]]:
    """Calls the proximity LLM to cluster hypotheses by similarity.

    A single call analyzes the whole pool at once; LOW_TEMPERATURE keeps
    clustering decisions consistent across cache-hit reruns.

    Args:
        state: Current workflow state.
        hypotheses: All hypotheses being analyzed for proximity.

    Returns:
        Similarity clusters as returned by the proximity LLM call (empty
        if the response was malformed or contained none).
    """
    hypotheses_for_analysis = _prepare_hypotheses_for_analysis(hypotheses)
    supervisor_guidance = state.get("supervisor_guidance")

    prompt, schema = get_proximity_prompt(
        hypotheses_for_analysis, supervisor_guidance=supervisor_guidance
    )

    response = await _call_proximity_llm(state, prompt, schema, len(hypotheses))

    similarity_clusters: list[dict[str, Any]] = response.get(
        "similarity_clusters", []
    )
    return similarity_clusters


def _log_dedup_summary(
    original_count: int,
    kept_count: int,
    removed_duplicates: list[dict[str, Any]],
) -> None:
    """Logs a summary of proximity deduplication results.

    One info row per pass, carrying the count. The drops themselves are
    traced individually -- and only at debug -- where they are decided, in
    ``proximity_dedup._build_removed_duplicates_for_cluster``; a second
    sample of the same event here said nothing that record did not.

    Args:
        original_count: Number of hypotheses before deduplication.
        kept_count: Number of hypotheses retained after deduplication.
        removed_duplicates: Duplicates removed during this pass.
    """
    logger.info(
        "Proximity analysis complete: %s → %s hypotheses"
        " (%s duplicates removed)",
        original_count,
        kept_count,
        len(removed_duplicates),
    )


@dataclass
class _ClusteringOutcome:
    """Bundled output of one proximity clustering + dedup pass.

    Attributes:
        hypotheses_to_keep: Hypotheses retained after deduplication.
        removed_duplicates: Audit records for hypotheses dropped this pass.
        similarity_clusters: Clusters as returned by the proximity LLM call.
    """

    hypotheses_to_keep: list[Hypothesis]
    removed_duplicates: list[dict[str, Any]]
    similarity_clusters: list[dict[str, Any]]


def _finish_clustering(
    hypotheses: list[Hypothesis], similarity_clusters: list[dict[str, Any]]
) -> _ClusteringOutcome:
    """Assigns cluster ids in place, dedupes, and logs the pass's summary."""
    _assign_cluster_ids(hypotheses, similarity_clusters)
    hypotheses_to_keep, removed_duplicates = _dedupe_by_cluster(hypotheses)
    _log_dedup_summary(
        len(hypotheses), len(hypotheses_to_keep), removed_duplicates
    )
    return _ClusteringOutcome(
        hypotheses_to_keep, removed_duplicates, similarity_clusters
    )


async def _run_proximity_clustering(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
) -> "_ClusteringOutcome | None":
    """Runs one LLM clustering + dedup pass for proximity_node.

    Emits the "proximity_start" progress event, then calls the proximity LLM
    and resolves cluster duplicates.

    Args:
        state: Current workflow state.
        hypotheses: All hypotheses being analyzed for proximity.

    Returns:
        The clustering outcome, or None if the LLM returned no similarity
        clusters -- a malformed or empty response -- so the caller can skip
        deduplication for this iteration rather than failing the whole run.
    """
    await emit_progress(
        state,
        "proximity_start",
        f"Analyzing similarity of {len(hypotheses)} hypotheses...",
        PROGRESS_PROXIMITY_START,
    )

    similarity_clusters = await _fetch_similarity_clusters(state, hypotheses)

    if not similarity_clusters:
        logger.warning(
            "No similarity clusters returned, skipping deduplication"
        )
        return None

    return _finish_clustering(hypotheses, similarity_clusters)


def _survivor_index(
    hypotheses: list[Hypothesis], outcome: _ClusteringOutcome
) -> SurvivorIndex:
    """Builds the graph's member-resolution tables over the dedup survivors.

    ``by_index`` is keyed by each hypothesis's position in the pool the
    prompt numbered (``_prepare_hypotheses_for_analysis``), which is what a
    live ``PROXIMITY_SCHEMA`` response names its members by. Removed
    duplicates are simply left out rather than renumbering the survivors,
    so an index still means the same hypothesis it did in the prompt while
    a dropped member resolves to nothing. ``by_text`` keeps the older
    echoed-text fallback, keyed by member_match_key so a cluster member the
    LLM re-quotes resolves the same way the node's clustering resolves it.

    Args:
        hypotheses: The pool before this pass's deduplication, in the order
            the prompt numbered it.
        outcome: Result of this pass's clustering and deduplication.

    Returns:
        Resolution tables covering only the surviving hypotheses.
    """
    kept_ids = {h.id for h in outcome.hypotheses_to_keep}
    return SurvivorIndex(
        by_index={
            index: hyp.id
            for index, hyp in enumerate(hypotheses)
            if hyp.id in kept_ids
        },
        by_text={
            member_match_key(h.text): h.id for h in outcome.hypotheses_to_keep
        },
    )


def _build_updated_proximity_graph(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    outcome: _ClusteringOutcome,
) -> dict[str, Any]:
    """Builds the persisted weighted proximity graph for this pass's clusters.

    Edges over the kept hypotheses carry a similarity score and
    method/model/goal/update-time provenance (Milestone 3).
    """
    return build_proximity_graph(
        outcome.similarity_clusters,
        _survivor_index(hypotheses, outcome),
        research_goal=state["research_goal"],
        model=state["model_name"],
        updated_at=time.time(),
    )


def _proximity_update_message(
    hypotheses: list[Hypothesis], outcome: _ClusteringOutcome
) -> list[dict[str, Any]]:
    """Builds this pass's phase_message payload for the state delta."""
    return phase_message(
        "proximity",
        f"Deduplication: {len(hypotheses)}"
        f" → {len(outcome.hypotheses_to_keep)}"
        f" ({len(outcome.removed_duplicates)} removed)",
        duplicates_removed=len(outcome.removed_duplicates),
        clusters=len(outcome.similarity_clusters),
    )


def _build_proximity_update(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    outcome: _ClusteringOutcome,
) -> dict[str, Any]:
    """Builds the proximity_node state update for a completed pass.

    Appends this pass's removed duplicates onto the running list rather
    than replacing it, so removed_duplicates accumulates the full history
    across iterations. outcome.hypotheses_to_keep is a strict subset of
    `hypotheses` (same ids, no new hypotheses introduced), so this bare-list
    return REPLACEs the pool via deduplicate_hypotheses (state.py), pruning
    the removed duplicates. The iteration counter is owned by the
    orchestrator, not advanced here.

    Args:
        state: Current workflow state.
        hypotheses: The hypotheses pool before this pass's deduplication.
        outcome: Result of _run_proximity_clustering.

    Returns:
        Dictionary with updated state fields (deduplicated hypotheses).
    """
    metrics = create_metrics_update(deltas=MetricDeltas(llm_calls=1))
    all_removed_duplicates = (
        state.get("removed_duplicates", []) + outcome.removed_duplicates
    )
    proximity_graph = _build_updated_proximity_graph(state, hypotheses, outcome)

    return {
        "hypotheses": outcome.hypotheses_to_keep,
        "removed_duplicates": all_removed_duplicates,
        "proximity_graph": proximity_graph,
        "metrics": metrics,
        "messages": _proximity_update_message(hypotheses, outcome),
    }


async def _emit_proximity_complete(
    state: WorkflowState, outcome: _ClusteringOutcome
) -> None:
    """Emits the proximity_complete progress event for a finished pass."""
    await emit_progress(
        state,
        "proximity_complete",
        f"Removed {len(outcome.removed_duplicates)} duplicates",
        PROGRESS_PROXIMITY_COMPLETE,
        duplicates_removed=len(outcome.removed_duplicates),
        remaining=len(outcome.hypotheses_to_keep),
    )


async def proximity_node(state: WorkflowState) -> dict[str, Any]:
    """Clusters hypotheses by similarity and removes high-similarity duplicates.

    This node uses LLM-based semantic similarity analysis to:
    1. Cluster hypotheses by conceptual similarity
    2. Identify "high" similarity duplicates
    3. Remove duplicates, keeping the best from each cluster
    4. Track removed duplicates

    Args:
        state: Current workflow state

    Returns:
        Dictionary with updated state fields (deduplicated hypotheses)
    """
    hypotheses = state["hypotheses"]
    logger.info("Analyzing proximity of %s hypotheses", len(hypotheses))

    # Similarity clustering needs at least two hypotheses to compare, so
    # skip the LLM call entirely for an empty or singleton pool.
    if len(hypotheses) <= 1:
        logger.info("Not enough hypotheses for proximity analysis")
        return {"hypotheses": hypotheses}

    # Malformed or empty LLM output: skip deduplication for this iteration
    # rather than raising, so a bad response degrades gracefully instead
    # of failing the whole run.
    outcome = await _run_proximity_clustering(state, hypotheses)
    if outcome is None:
        return {"hypotheses": hypotheses}

    await _emit_proximity_complete(state, outcome)

    return _build_proximity_update(state, hypotheses, outcome)
