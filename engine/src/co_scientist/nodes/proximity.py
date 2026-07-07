"""Proximity node - cluster and deduplicate similar hypotheses."""
# pylint: disable=inconsistent-quotes

import logging
from typing import Any

from co_scientist.constants import (
    LONG_MAX_TOKENS,
    LOW_TEMPERATURE,
    PROGRESS_PROXIMITY_START,
    PROGRESS_PROXIMITY_COMPLETE,
)
from co_scientist.llm import call_llm_json
from co_scientist.models import Hypothesis, create_metrics_update, rank_by_elo
from co_scientist.nodes.progress import emit_progress
from co_scientist.prompts import get_proximity_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


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

    current_iteration = state.get("current_iteration", 0)
    next_iteration = current_iteration + 1

    if len(hypotheses) <= 1:
        logger.info("Not enough hypotheses for proximity analysis")
        return {"hypotheses": hypotheses, "current_iteration": next_iteration}

    # Emit progress
    await emit_progress(
        state, "proximity_start",
        f"Analyzing similarity of {len(hypotheses)} hypotheses...",
        PROGRESS_PROXIMITY_START)

    # Prepare hypotheses for similarity analysis
    hypotheses_for_analysis = [{
        "text": hyp.text,
        "score": hyp.score,
        "elo_rating": hyp.elo_rating,
        "index": i
    } for i, hyp in enumerate(hypotheses)]

    # Get supervisor guidance from state
    supervisor_guidance = state.get("supervisor_guidance")

    # Call LLM to cluster by similarity
    prompt, schema = get_proximity_prompt(
        hypotheses_for_analysis, supervisor_guidance=supervisor_guidance)

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

    similarity_clusters = response.get("similarity_clusters", [])

    if not similarity_clusters:
        logger.warning(
            "No similarity clusters returned, skipping deduplication")
        return {"hypotheses": hypotheses, "current_iteration": next_iteration}

    # Assign cluster IDs to hypotheses
    for cluster in similarity_clusters:
        cluster_id = cluster.get("cluster_id", "unknown")
        similar_hypotheses = cluster.get("similar_hypotheses", [])

        for similar_hyp in similar_hypotheses:
            hyp_text = similar_hyp.get("text", "")
            similarity_degree = similar_hyp.get("similarity_degree", "low")

            # Find matching hypothesis
            for hyp in hypotheses:
                # Match by text (first 100 chars for robustness)
                if hyp.text[:100] == hyp_text[:100]:
                    hyp.similarity_cluster_id = cluster_id
                    # Store similarity degree (only set if not already set)
                    if hyp.similarity_degree is None:
                        hyp.similarity_degree = similarity_degree
                    break

    # Identify and remove high-similarity duplicates
    removed_duplicates: list[dict[str, Any]] = []
    hypotheses_to_keep: list[Hypothesis] = []

    # Group by cluster
    clusters_dict: dict[str, list[Hypothesis]] = {}
    for hyp in hypotheses:
        cluster_id = hyp.similarity_cluster_id or "unclustered"
        if cluster_id not in clusters_dict:
            clusters_dict[cluster_id] = []
        clusters_dict[cluster_id].append(hyp)

    # For each cluster, handle high-similarity duplicates
    for cluster_id, cluster_hypotheses in clusters_dict.items():
        if len(cluster_hypotheses) == 1:
            # No duplicates possible
            hypotheses_to_keep.extend(cluster_hypotheses)
            continue

        # Separate by similarity degree
        high_similarity = [
            h for h in cluster_hypotheses if h.similarity_degree == "high"
        ]
        others = [
            h for h in cluster_hypotheses if h.similarity_degree != "high"
        ]

        # Keep all non-high-similarity hypotheses
        hypotheses_to_keep.extend(others)

        if high_similarity:
            # For high-similarity duplicates, keep only the best. Rank by Elo
            # (primary), then score, then text as deterministic tiebreakers.
            high_similarity[:] = rank_by_elo(high_similarity)

            # Keep the best
            best = high_similarity[0]
            hypotheses_to_keep.append(best)

            # Remove the rest
            for duplicate in high_similarity[1:]:
                removed_duplicates.append({
                    "text": duplicate.text,
                    "cluster_id": cluster_id,
                    "reason": "high_similarity_duplicate",
                    "kept_instead": best.text[:200],
                    "elo_rating": duplicate.elo_rating,
                    "score": duplicate.score,
                })
                logger.info(
                    "Removed duplicate from cluster %s: %s... (Elo: %s)",
                    cluster_id, duplicate.text[:100], duplicate.elo_rating)

    logger.info(
        "Proximity analysis complete: %s → %s hypotheses"
        " (%s duplicates removed)", len(hypotheses), len(hypotheses_to_keep),
        len(removed_duplicates))

    if removed_duplicates:
        logger.warning("Removed %s high-similarity duplicates:",
                       len(removed_duplicates))
        for dup in removed_duplicates[:3]:  # Log first 3
            logger.warning("- %s...", dup['text'][:80])

    # Emit progress
    await emit_progress(state,
                        "proximity_complete",
                        f"Removed {len(removed_duplicates)} duplicates",
                        PROGRESS_PROXIMITY_COMPLETE,
                        duplicates_removed=len(removed_duplicates),
                        remaining=len(hypotheses_to_keep))

    # Update metrics (deltas only, merge_metrics will add to existing state)
    metrics = create_metrics_update(llm_calls_delta=1)

    # Update removed duplicates list
    all_removed_duplicates = state.get("removed_duplicates",
                                       []) + removed_duplicates

    return {
        "hypotheses":
            hypotheses_to_keep,
        "removed_duplicates":
            all_removed_duplicates,
        "similarity_clusters":
            similarity_clusters,
        "metrics":
            metrics,
        "current_iteration":
            next_iteration,
        "messages": [{
            "role": "assistant",
            "content": (f"Deduplication: {len(hypotheses)}"
                        f" → {len(hypotheses_to_keep)}"
                        f" ({len(removed_duplicates)} removed)"),
            "metadata": {
                "phase": "proximity",
                "duplicates_removed": len(removed_duplicates),
                "clusters": len(similarity_clusters),
            },
        }],
    }
