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
from co_scientist.models import (Hypothesis, create_metrics_update,
                                 phase_message, rank_by_elo)
from co_scientist.nodes.progress import emit_progress
from co_scientist.prompts import get_proximity_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


def _assign_cluster_ids(hypotheses: list[Hypothesis],
                        similarity_clusters: list[dict[str, Any]]) -> None:
    """Assigns similarity-cluster ids and degrees back onto hypotheses.

    The LLM echoes back hypothesis text per cluster rather than an index,
    so hypotheses are re-matched here by comparing the first 100 chars of
    text -- cheap, and robust to minor whitespace or formatting drift the
    LLM may introduce when quoting. Mutates the hypotheses in place.

    Args:
        hypotheses: All hypotheses being analyzed for proximity.
        similarity_clusters: Clusters as returned by the proximity LLM call.
    """
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
                    # First match wins: if the LLM's clusters overlap and a
                    # hypothesis appears more than once, its degree is
                    # fixed by whichever cluster is processed first rather
                    # than being overwritten by later matches.
                    if hyp.similarity_degree is None:
                        hyp.similarity_degree = similarity_degree
                    break


def _resolve_cluster_duplicates(
    cluster_id: str, cluster_hypotheses: list[Hypothesis]
) -> tuple[list[Hypothesis], list[dict[str, Any]]]:
    """Resolves high-similarity duplicates within a single cluster.

    Keeps every non-"high" similarity hypothesis plus only the single best
    "high" similarity hypothesis (ranked by Elo, then score, then text),
    recording the rest as removed duplicates.

    Args:
        cluster_id: Identifier of the cluster being resolved.
        cluster_hypotheses: Hypotheses assigned to this cluster.

    Returns:
        Tuple of (hypotheses_to_keep, removed_duplicates) for this cluster.
    """
    if len(cluster_hypotheses) == 1:
        # No duplicates possible
        return list(cluster_hypotheses), []

    hypotheses_to_keep: list[Hypothesis] = []
    removed_duplicates: list[dict[str, Any]] = []

    # Separate by similarity degree
    # Only hypotheses tagged "high" are candidates for removal;
    # "medium"/"low" degree hypotheses in the same cluster are related
    # but distinct enough to keep both.
    high_similarity = [
        h for h in cluster_hypotheses if h.similarity_degree == "high"
    ]
    others = [h for h in cluster_hypotheses if h.similarity_degree != "high"]

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
        # Every other high-similarity hypothesis in the cluster is
        # dropped; record what was removed, why, and what was kept
        # instead for the removed_duplicates audit trail (state.py),
        # which evolve.py later reads to avoid recreating them and the
        # UI surfaces for transparency.
        for duplicate in high_similarity[1:]:
            removed_duplicates.append({
                "text": duplicate.text,
                "cluster_id": cluster_id,
                "reason": "high_similarity_duplicate",
                "kept_instead": best.text[:200],
                "elo_rating": duplicate.elo_rating,
                "score": duplicate.score,
            })
            logger.info("Removed duplicate from cluster %s: %s... (Elo: %s)",
                        cluster_id, duplicate.text[:100], duplicate.elo_rating)

    return hypotheses_to_keep, removed_duplicates


def _dedupe_by_cluster(
    hypotheses: list[Hypothesis]
) -> tuple[list[Hypothesis], list[dict[str, Any]]]:
    """Removes high-similarity duplicates within each similarity cluster.

    Groups hypotheses by their (already-assigned) similarity_cluster_id,
    then for each cluster keeps every non-"high" similarity hypothesis plus
    only the single best "high" similarity hypothesis (ranked by Elo, then
    score, then text), recording the rest as removed duplicates.

    Args:
        hypotheses: All hypotheses being analyzed for proximity, with
            similarity_cluster_id/similarity_degree already assigned.

    Returns:
        Tuple of (hypotheses_to_keep, removed_duplicates), where
        removed_duplicates entries feed the audit trail that evolve.py
        later reads to avoid recreating them and the UI surfaces for
        transparency.
    """
    removed_duplicates: list[dict[str, Any]] = []
    hypotheses_to_keep: list[Hypothesis] = []

    # Group by cluster
    # Rebuilt from each hypothesis's own similarity_cluster_id (rather
    # than reusing the LLM's similarity_clusters list directly), so every
    # hypothesis -- including any the LLM left unclustered -- is
    # accounted for exactly once below.
    clusters_dict: dict[str, list[Hypothesis]] = {}
    for hyp in hypotheses:
        cluster_id = hyp.similarity_cluster_id or "unclustered"
        if cluster_id not in clusters_dict:
            clusters_dict[cluster_id] = []
        clusters_dict[cluster_id].append(hyp)

    # For each cluster, handle high-similarity duplicates
    for cluster_id, cluster_hypotheses in clusters_dict.items():
        kept, removed = _resolve_cluster_duplicates(cluster_id,
                                                    cluster_hypotheses)
        hypotheses_to_keep.extend(kept)
        removed_duplicates.extend(removed)

    return hypotheses_to_keep, removed_duplicates


async def _fetch_similarity_clusters(
        state: WorkflowState,
        hypotheses: list[Hypothesis]) -> list[dict[str, Any]]:
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
    # Prepare hypotheses for similarity analysis
    # Send only the fields the clustering prompt needs, plus a positional
    # `index` used only for prompt authoring; matching responses back to
    # Hypothesis objects below is done by text prefix, not this index.
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

    similarity_clusters: list[dict[str,
                                   Any]] = response.get("similarity_clusters",
                                                        [])
    return similarity_clusters


def _log_dedup_summary(original_count: int, kept_count: int,
                       removed_duplicates: list[dict[str, Any]]) -> None:
    """Logs a summary of proximity deduplication results.

    Args:
        original_count: Number of hypotheses before deduplication.
        kept_count: Number of hypotheses retained after deduplication.
        removed_duplicates: Duplicates removed during this pass.
    """
    logger.info(
        "Proximity analysis complete: %s → %s hypotheses"
        " (%s duplicates removed)", original_count, kept_count,
        len(removed_duplicates))

    if removed_duplicates:
        logger.warning("Removed %s high-similarity duplicates:",
                       len(removed_duplicates))
        for dup in removed_duplicates[:3]:  # Log first 3
            logger.warning("- %s...", dup['text'][:80])


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

    # proximity_node runs once per workflow iteration; advance the counter
    # here unconditionally, regardless of whether clustering runs below.
    current_iteration = state.get("current_iteration", 0)
    next_iteration = current_iteration + 1

    # Similarity clustering needs at least two hypotheses to compare, so
    # skip the LLM call entirely for an empty or singleton pool.
    if len(hypotheses) <= 1:
        logger.info("Not enough hypotheses for proximity analysis")
        return {"hypotheses": hypotheses, "current_iteration": next_iteration}

    # Emit progress
    await emit_progress(
        state, "proximity_start",
        f"Analyzing similarity of {len(hypotheses)} hypotheses...",
        PROGRESS_PROXIMITY_START)

    # Call LLM to cluster by similarity
    similarity_clusters = await _fetch_similarity_clusters(state, hypotheses)

    # Malformed or empty LLM output: skip deduplication for this iteration
    # rather than raising, so a bad response degrades gracefully instead
    # of failing the whole run.
    if not similarity_clusters:
        logger.warning(
            "No similarity clusters returned, skipping deduplication")
        return {"hypotheses": hypotheses, "current_iteration": next_iteration}

    # Assign cluster IDs to hypotheses
    _assign_cluster_ids(hypotheses, similarity_clusters)

    # Identify and remove high-similarity duplicates
    hypotheses_to_keep, removed_duplicates = _dedupe_by_cluster(hypotheses)

    _log_dedup_summary(len(hypotheses), len(hypotheses_to_keep),
                       removed_duplicates)

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
    # Appended onto the running list rather than replacing it, so
    # removed_duplicates accumulates the full history across iterations.
    all_removed_duplicates = state.get("removed_duplicates",
                                       []) + removed_duplicates

    # hypotheses_to_keep is a strict subset of the incoming hypotheses
    # (same text, no new hypotheses introduced), so this update is always
    # >50% overlap with existing state and deduplicate_hypotheses
    # (state.py) treats it as a replacement rather than an addition --
    # unlike evolve.py's return, there is no risk of discarded duplicates
    # resurfacing via the reducer's merge path.
    return {
        "hypotheses":
            hypotheses_to_keep,
        "removed_duplicates":
            all_removed_duplicates,
        "metrics":
            metrics,
        "current_iteration":
            next_iteration,
        "messages":
            phase_message("proximity", f"Deduplication: {len(hypotheses)}"
                          f" → {len(hypotheses_to_keep)}"
                          f" ({len(removed_duplicates)} removed)",
                          duplicates_removed=len(removed_duplicates),
                          clusters=len(similarity_clusters)),
    }
