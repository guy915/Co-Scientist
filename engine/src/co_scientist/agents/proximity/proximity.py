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
    build_proximity_graph,
    member_match_key,
)
from co_scientist.constants import (
    LONG_MAX_TOKENS,
    LOW_TEMPERATURE,
    PROGRESS_PROXIMITY_COMPLETE,
    PROGRESS_PROXIMITY_START,
)
from co_scientist.llm import call_llm_json
from co_scientist.models import (
    Hypothesis,
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

    Sends only the fields the clustering prompt needs, plus a positional
    `index` used only for prompt authoring; matching responses back to
    Hypothesis objects is done by text prefix, not this index (see
    _assign_cluster_ids).

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

    # Get supervisor guidance from state
    supervisor_guidance = state.get("supervisor_guidance")

    # Call LLM to cluster by similarity
    prompt, schema = get_proximity_prompt(
        hypotheses_for_analysis, supervisor_guidance=supervisor_guidance
    )

    response = await call_llm_json(
        prompt=prompt,
        model_name=state["model_name"],
        max_tokens=LONG_MAX_TOKENS,
        temperature=LOW_TEMPERATURE,
        json_schema=schema,
        run_id=state.get("run_id"),
        prompt_name="proximity",
        prompt_metadata={
            "prompt_length_chars": len(prompt),
            "hypotheses_count": len(hypotheses),
        },
    )

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

    if removed_duplicates:
        logger.warning(
            "Removed %s high-similarity duplicates:", len(removed_duplicates)
        )
        for dup in removed_duplicates[:3]:  # Log first 3
            logger.warning("- %s...", dup["text"][:80])


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


async def _run_proximity_clustering(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
) -> "_ClusteringOutcome | None":
    """Runs one LLM clustering + dedup pass for proximity_node.

    Emits the "proximity_start" progress event, then calls the proximity LLM
    and resolves cluster duplicates. Assigns cluster ids onto `hypotheses`
    in place.

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

    _assign_cluster_ids(hypotheses, similarity_clusters)

    hypotheses_to_keep, removed_duplicates = _dedupe_by_cluster(hypotheses)

    _log_dedup_summary(
        len(hypotheses), len(hypotheses_to_keep), removed_duplicates
    )

    return _ClusteringOutcome(
        hypotheses_to_keep, removed_duplicates, similarity_clusters
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
    metrics = create_metrics_update(llm_calls_delta=1)

    all_removed_duplicates = (
        state.get("removed_duplicates", []) + outcome.removed_duplicates
    )

    # Build the persisted weighted proximity graph from this pass's clusters
    # (Milestone 3): edges over the kept hypotheses carry a similarity score
    # and method/model/goal/update-time provenance. The id map is keyed by
    # member_match_key so a cluster member echoed by the LLM resolves to its
    # surviving hypothesis the same way the node's clustering does.
    id_by_text = {
        member_match_key(h.text): h.id for h in outcome.hypotheses_to_keep
    }
    proximity_graph = build_proximity_graph(
        outcome.similarity_clusters,
        id_by_text,
        research_goal=state["research_goal"],
        model=state["model_name"],
        updated_at=time.time(),
    )

    return {
        "hypotheses": outcome.hypotheses_to_keep,
        "removed_duplicates": all_removed_duplicates,
        "proximity_graph": proximity_graph,
        "metrics": metrics,
        "messages": phase_message(
            "proximity",
            f"Deduplication: {len(hypotheses)}"
            f" → {len(outcome.hypotheses_to_keep)}"
            f" ({len(outcome.removed_duplicates)} removed)",
            duplicates_removed=len(outcome.removed_duplicates),
            clusters=len(outcome.similarity_clusters),
        ),
    }


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

    # Emit progress
    await emit_progress(
        state,
        "proximity_complete",
        f"Removed {len(outcome.removed_duplicates)} duplicates",
        PROGRESS_PROXIMITY_COMPLETE,
        duplicates_removed=len(outcome.removed_duplicates),
        remaining=len(outcome.hypotheses_to_keep),
    )

    return _build_proximity_update(state, hypotheses, outcome)
